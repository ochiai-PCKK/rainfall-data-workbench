from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

from .errors import ZipFlowError
from .graph_builder import build_metric_frame, render_region_plots_reference
from .logger import build_logger
from .style_profile import load_style_profile

_DATE_SHEET_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2}$")
_RESPLIT_PREFIX = "【再分割】"
_REGION_KEY_EXCEL_DEFAULT = "nishiyoke_higashiyoke"
_REGION_LABEL_EXCEL_DEFAULT = "西除川+東除川"


@dataclass(frozen=True)
class ExcelRunConfig:
    input_excel: Path
    output_root: Path
    selected_sheets: tuple[str, ...]
    graph_span: str  # 5d | 3d_left | 3d_center | 3d_right
    ref_graph_kinds: tuple[str, ...]  # sum | mean
    export_svg: bool
    enable_log: bool
    style_profile_path: Path | None = None
    on_conflict: str = "rename"
    region_key: str = _REGION_KEY_EXCEL_DEFAULT
    region_label: str = _REGION_LABEL_EXCEL_DEFAULT


def parse_event_sheet_date(sheet_name: str) -> date | None:
    raw = sheet_name.strip()
    if raw.startswith(_RESPLIT_PREFIX):
        raw = raw.replace(_RESPLIT_PREFIX, "", 1)
    if not _DATE_SHEET_RE.fullmatch(raw):
        return None
    try:
        return datetime.strptime(raw, "%Y.%m.%d").date()
    except ValueError:
        return None


def resolve_effective_base_date(base_date: date, graph_span: str) -> date:
    if graph_span == "3d_left":
        return base_date - timedelta(days=1)
    if graph_span == "3d_right":
        return base_date + timedelta(days=1)
    return base_date


def _to_datetime(value: object, *, row_no: int, sheet_name: str) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time(hour=0))
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ZipFlowError(
            f"Excel時刻列(B列)の解釈に失敗しました: sheet={sheet_name} row={row_no}",
            exit_code=5,
        )
    return pd.Timestamp(parsed).to_pydatetime()


def _to_float(value: object, *, row_no: int, sheet_name: str) -> float:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        raise ZipFlowError(
            f"Excel雨量列(Q列)の数値変換に失敗しました: sheet={sheet_name} row={row_no}",
            exit_code=5,
        )
    return float(parsed)


def _load_sheet_series(excel_path: Path, *, sheet_name: str, base_date: date) -> pd.DataFrame:
    wb = load_workbook(excel_path, data_only=True, read_only=True)
    if sheet_name not in wb.sheetnames:
        raise ZipFlowError(f"指定シートが存在しません: {sheet_name}", exit_code=5)
    ws = wb[sheet_name]
    rows: list[dict[str, object]] = []
    for row_no, values in enumerate(ws.iter_rows(min_row=5, max_col=17, values_only=True), start=5):
        b = values[1] if len(values) > 1 else None
        q = values[16] if len(values) > 16 else None
        if b is None and q is None:
            continue
        if b is None or q is None:
            raise ZipFlowError(
                f"Excel時系列に欠損行があります(B/Q片側欠損): sheet={sheet_name} row={row_no}",
                exit_code=5,
            )
        observed = _to_datetime(b, row_no=row_no, sheet_name=sheet_name)
        rainfall = _to_float(q, row_no=row_no, sheet_name=sheet_name)
        rows.append({"observed_at": observed, "rainfall_mm": rainfall})

    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ZipFlowError(f"Excel時系列が空です: sheet={sheet_name}", exit_code=5)
    if len(frame) != 120:
        raise ZipFlowError(
            f"Excel時系列点数が120ではありません: sheet={sheet_name} expected=120 actual={len(frame)}",
            exit_code=5,
        )

    if frame["observed_at"].duplicated().any():
        raise ZipFlowError(f"Excel時刻列に重複があります: sheet={sheet_name}", exit_code=5)
    if not frame["observed_at"].is_monotonic_increasing:
        raise ZipFlowError(f"Excel時刻列が昇順ではありません: sheet={sheet_name}", exit_code=5)

    diffs = frame["observed_at"].diff().dropna()
    if not diffs.eq(timedelta(hours=1)).all():
        raise ZipFlowError(f"Excel時刻列が1時間間隔ではありません: sheet={sheet_name}", exit_code=5)

    expected_start = datetime.combine(base_date - timedelta(days=2), time(hour=1))
    expected_end = datetime.combine(base_date + timedelta(days=3), time(hour=0))
    actual_start = pd.Timestamp(frame["observed_at"].iloc[0]).to_pydatetime()
    actual_end = pd.Timestamp(frame["observed_at"].iloc[-1]).to_pydatetime()
    if actual_start != expected_start or actual_end != expected_end:
        raise ZipFlowError(
            "Excel時系列の期間がシート日付と一致しません: "
            f"sheet={sheet_name} expected={expected_start:%Y-%m-%d %H:%M}..{expected_end:%Y-%m-%d %H:%M} "
            f"actual={actual_start:%Y-%m-%d %H:%M}..{actual_end:%Y-%m-%d %H:%M}",
            exit_code=5,
        )
    # Excel側の1時間は「01:00〜翌00:00」表記のため、グラフ系は0時起点へ正規化して扱う。
    frame["observed_at"] = frame["observed_at"] - timedelta(hours=1)
    return frame


def run_excel_mode(config: ExcelRunConfig) -> dict[str, object]:
    if not config.input_excel.exists():
        raise ZipFlowError(f"入力Excelファイルが見つかりません: {config.input_excel}", exit_code=2)
    if not config.selected_sheets:
        raise ZipFlowError("Excelモードではイベント候補を1件以上選択してください。", exit_code=2)
    if config.graph_span not in ("5d", "3d_left", "3d_center", "3d_right"):
        raise ZipFlowError(f"未対応の graph_span です: {config.graph_span}", exit_code=2)
    if not config.ref_graph_kinds:
        raise ZipFlowError("グラフ指標を1つ以上選択してください。", exit_code=2)

    plot_ref_dir = config.output_root / "plots_reference"
    plot_ref_dir.mkdir(parents=True, exist_ok=True)
    log_dir = config.output_root / "logs"
    if config.enable_log:
        log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "excel_mode.log"
    logger = build_logger(enable_file=config.enable_log, log_path=log_path)
    logger.info("Excelモード実行開始: input=%s", config.input_excel)
    logger.info("選択シート: %s", list(config.selected_sheets))

    style_profile = None
    try:
        style_profile = load_style_profile(config.style_profile_path)
    except Exception as exc:  # noqa: BLE001
        raise ZipFlowError(f"スタイル読込に失敗しました: {exc}", exit_code=2) from exc

    saved: list[Path] = []
    for sheet_name in config.selected_sheets:
        base_date = parse_event_sheet_date(sheet_name)
        if base_date is None:
            raise ZipFlowError(f"シート名の日付解釈に失敗しました: {sheet_name}", exit_code=5)
        effective_base_date = resolve_effective_base_date(base_date, config.graph_span)
        render_span = "5d"
        if config.graph_span != "5d":
            render_span = "3d"
        frame_src = _load_sheet_series(config.input_excel, sheet_name=sheet_name, base_date=base_date)
        observed_at = frame_src["observed_at"].tolist()
        rainfall = frame_src["rainfall_mm"].astype(float).tolist()
        frame_sum = build_metric_frame(observed_at=observed_at, weighted_sum=rainfall)
        frame_mean = build_metric_frame(observed_at=observed_at, weighted_sum=rainfall)
        logger.info(
            "シート検証OK: %s points=%s range=%s..%s",
            sheet_name,
            len(frame_src),
            frame_src["observed_at"].min(),
            frame_src["observed_at"].max(),
        )
        outputs = render_region_plots_reference(
            frame_sum=frame_sum,
            frame_mean=frame_mean,
            region_key=config.region_key,
            region_label=config.region_label,
            output_dir=plot_ref_dir,
            base_date=effective_base_date,
            graph_spans=(render_span,),
            ref_graph_kinds=config.ref_graph_kinds,
            export_svg=config.export_svg,
            on_conflict=config.on_conflict,
            style=style_profile,
        )
        saved.extend(outputs)
        logger.info("グラフ出力完了: sheet=%s files=%s", sheet_name, len(outputs))

    logger.info("Excelモード完了: plot_count=%s", len(saved))
    return {
        "base_dir": str(config.output_root),
        "plot_ref_dir": str(plot_ref_dir),
        "log_path": str(log_path) if config.enable_log else None,
        "zip_count": 0,
        "plot_count": len(saved),
        "csv_count": 0,
        "cell_csv_count": 0,
        "csv_readme_path": None,
        "event_count": len(config.selected_sheets),
    }
