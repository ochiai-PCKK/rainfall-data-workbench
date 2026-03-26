# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportReturnType=false
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd

from uc_rainfall.graph.chart_renderer import render_metric_chart

from .graph_renderer_reference import render_reference_chart
from .style_profile import GraphStyleProfile

LOGGER = logging.getLogger("uc_rainfall_zipflow")

METRIC_WINDOWS = {
    "1h": 1,
    "3h": 3,
    "6h": 6,
    "12h": 12,
    "24h": 24,
    "48h": 48,
}


def build_reference_output_paths(
    *,
    output_dir: Path,
    region_keys: tuple[str, ...],
    base_date: date,
    graph_spans: tuple[str, ...],
    ref_graph_kinds: tuple[str, ...],
    export_svg: bool,
    filename_prefix: str = "",
) -> list[Path]:
    paths: list[Path] = []
    for region_key in region_keys:
        for span in graph_spans:
            if "sum" in ref_graph_kinds:
                paths.append(output_dir / f"{filename_prefix}{region_key}_{base_date:%Y%m%d}_{span}_sum_overview.png")
            if "mean" in ref_graph_kinds:
                paths.append(output_dir / f"{filename_prefix}{region_key}_{base_date:%Y%m%d}_{span}_mean_overview.png")
            if export_svg:
                if "sum" in ref_graph_kinds:
                    paths.append(
                        output_dir / f"{filename_prefix}{region_key}_{base_date:%Y%m%d}_{span}_sum_overview.svg"
                    )
                if "mean" in ref_graph_kinds:
                    paths.append(
                        output_dir / f"{filename_prefix}{region_key}_{base_date:%Y%m%d}_{span}_mean_overview.svg"
                    )
    return paths


def _resolve_output_path(path: Path, *, on_conflict: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        return path
    if on_conflict == "overwrite":
        return path
    if on_conflict == "cancel":
        raise FileExistsError(f"既存ファイルが存在します: {path}")
    if on_conflict != "rename":
        raise ValueError(f"未対応の on_conflict です: {on_conflict}")
    stem = path.stem
    suffix = path.suffix
    i = 2
    while True:
        candidate = path.with_name(f"{stem}_v{i}{suffix}")
        if not candidate.exists():
            return candidate
        i += 1


@dataclass(frozen=True)
class MetricPeak:
    metric: str
    occurred_at: pd.Timestamp
    value: float
    duplicates: tuple[pd.Timestamp, ...]


def build_metric_frame(observed_at: list, weighted_sum: list[float]) -> pd.DataFrame:
    """重み付き合計系列から指標列を生成する。"""
    frame = pd.DataFrame({"observed_at": observed_at, "rainfall_mm": weighted_sum})
    frame["quality"] = frame["rainfall_mm"].apply(lambda v: "missing" if pd.isna(v) else "normal")
    frame["rainfall_mm"] = frame["rainfall_mm"].fillna(0.0)
    for metric, hours in METRIC_WINDOWS.items():
        frame[metric] = frame["rainfall_mm"].rolling(window=hours, min_periods=hours).sum()
    return frame


def find_metric_peaks(frame: pd.DataFrame) -> list[MetricPeak]:
    """各指標の最大イベントを抽出する。"""
    peaks: list[MetricPeak] = []
    for metric in METRIC_WINDOWS:
        series = frame[["observed_at", metric]].dropna()
        if series.empty:
            raise ValueError(f"{metric} の最大イベントを抽出できません。")
        max_value = float(series[metric].max())
        matched = series[series[metric] == max_value]
        occurred_at = pd.Timestamp(matched["observed_at"].iloc[0])
        duplicates = tuple(pd.Timestamp(v) for v in matched["observed_at"].iloc[1:].tolist())
        if duplicates:
            LOGGER.warning(
                "同値最大: metric=%s value=%.3f 採用=%s 非採用=%s",
                metric,
                max_value,
                occurred_at.strftime("%Y-%m-%d %H:%M:%S"),
                [item.strftime("%Y-%m-%d %H:%M:%S") for item in duplicates],
            )
        peaks.append(MetricPeak(metric=metric, occurred_at=occurred_at, value=max_value, duplicates=duplicates))
    return peaks


def render_region_plots(
    *,
    frame: pd.DataFrame,
    peaks: list[MetricPeak],
    region_key: str,
    region_label: str,
    output_dir: Path,
    on_conflict: str = "rename",
) -> list[Path]:
    """既存スタイルで領域の指標グラフを保存する。"""
    saved: list[Path] = []
    for peak in peaks:
        stamp = peak.occurred_at.strftime("%Y%m%d%H")
        out = output_dir / region_key / f"{region_key}_{peak.metric}_{stamp}.png"
        out = _resolve_output_path(out, on_conflict=on_conflict)
        title = f"{region_label} 重み付き合計雨量 {peak.metric} 最大={peak.value:.2f} mm"
        render_metric_chart(
            frame,
            metric=peak.metric,
            event_time=peak.occurred_at.to_pydatetime(),
            output_path=out,
            title=title,
        )
        saved.append(out)
    return saved


def render_region_plots_reference(
    *,
    frame_sum: pd.DataFrame,
    frame_mean: pd.DataFrame,
    region_key: str,
    region_label: str,
    output_dir: Path,
    base_date: date,
    graph_spans: tuple[str, ...],
    ref_graph_kinds: tuple[str, ...],
    export_svg: bool,
    on_conflict: str = "rename",
    style: GraphStyleProfile | None = None,
    filename_prefix: str = "",
    axis_tops: dict[tuple[str, str], tuple[float, float]] | None = None,
) -> list[Path]:
    """参考画像寄せスタイルで領域の合計/平均グラフを保存する。"""
    saved: list[Path] = []
    for span in graph_spans:
        span_days = 3 if span == "3d" else 5
        frame_sum_span = _extract_span_frame(frame_sum, base_date=base_date, span_days=span_days)
        frame_mean_span = _extract_span_frame(frame_mean, base_date=base_date, span_days=span_days)
        start_date = pd.to_datetime(frame_sum_span["observed_at"]).min().strftime("%Y.%m.%d")
        end_date = pd.to_datetime(frame_sum_span["observed_at"]).max().strftime("%Y.%m.%d")

        out_sum_png = output_dir / f"{filename_prefix}{region_key}_{base_date:%Y%m%d}_{span}_sum_overview.png"
        out_mean_png = output_dir / f"{filename_prefix}{region_key}_{base_date:%Y%m%d}_{span}_mean_overview.png"
        title_sum = f"重み付き合計雨量（{start_date} - {end_date}）"
        title_mean = f"流域平均雨量（{start_date} - {end_date}）"
        sum_tops = (axis_tops or {}).get((span, "sum"))
        mean_tops = (axis_tops or {}).get((span, "mean"))

        if "sum" in ref_graph_kinds:
            out_sum_png = _resolve_output_path(out_sum_png, on_conflict=on_conflict)
            render_reference_chart(
                frame_sum_span,
                output_path=out_sum_png,
                title=title_sum,
                style=style,
                left_top=sum_tops[0] if sum_tops is not None else None,
                right_top=sum_tops[1] if sum_tops is not None else None,
            )
            saved.append(out_sum_png)
        if "mean" in ref_graph_kinds:
            out_mean_png = _resolve_output_path(out_mean_png, on_conflict=on_conflict)
            render_reference_chart(
                frame_mean_span,
                output_path=out_mean_png,
                title=title_mean,
                style=style,
                left_top=mean_tops[0] if mean_tops is not None else None,
                right_top=mean_tops[1] if mean_tops is not None else None,
            )
            saved.append(out_mean_png)
        if export_svg:
            out_sum_svg = output_dir / f"{filename_prefix}{region_key}_{base_date:%Y%m%d}_{span}_sum_overview.svg"
            out_mean_svg = output_dir / f"{filename_prefix}{region_key}_{base_date:%Y%m%d}_{span}_mean_overview.svg"
            if "sum" in ref_graph_kinds:
                out_sum_svg = _resolve_output_path(out_sum_svg, on_conflict=on_conflict)
                render_reference_chart(
                    frame_sum_span,
                    output_path=out_sum_svg,
                    title=title_sum,
                    style=style,
                    left_top=sum_tops[0] if sum_tops is not None else None,
                    right_top=sum_tops[1] if sum_tops is not None else None,
                )
                saved.append(out_sum_svg)
            if "mean" in ref_graph_kinds:
                out_mean_svg = _resolve_output_path(out_mean_svg, on_conflict=on_conflict)
                render_reference_chart(
                    frame_mean_span,
                    output_path=out_mean_svg,
                    title=title_mean,
                    style=style,
                    left_top=mean_tops[0] if mean_tops is not None else None,
                    right_top=mean_tops[1] if mean_tops is not None else None,
                )
                saved.append(out_mean_svg)
    return saved


def _extract_span_frame(frame: pd.DataFrame, *, base_date: date, span_days: int) -> pd.DataFrame:
    hours = span_days * 24
    center = datetime.combine(base_date, time(hour=0))
    start = center - timedelta(days=span_days // 2)
    end = start + timedelta(hours=hours - 1)
    sub = frame[(frame["observed_at"] >= start) & (frame["observed_at"] <= end)].copy()
    if len(sub) != hours:
        raise ValueError(
            f"{span_days}日グラフ用データが不足しています: expected={hours} actual={len(sub)} "
            f"range={start:%Y-%m-%d %H:%M}..{end:%Y-%m-%d %H:%M}"
        )
    return sub
