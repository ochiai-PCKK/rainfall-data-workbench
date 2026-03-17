from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .application import run_zipflow
from .errors import ZipFlowError
from .models import RunConfig
from .style_tuner_gui import launch_style_tuner

_AVAILABLE_REGIONS = ("nishiyoke", "higashiyoke", "nishiyoke_higashiyoke", "yamatogawa")
_AVAILABLE_OUTPUTS = ("raster", "raster_bbox", "plots", "plots_ref", "timeseries_csv")
_AVAILABLE_GRAPH_SPANS = ("3d", "5d")
_AVAILABLE_REF_GRAPH_KINDS = ("sum", "mean")


def _parse_base_date(value: str):
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_optional_date(value: str | None):
    if value is None:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_csv_choices(*, raw: str, available: tuple[str, ...], option_name: str) -> tuple[str, ...]:
    items = tuple(part.strip() for part in raw.split(",") if part.strip())
    if not items:
        raise ValueError(f"{option_name} に値がありません。")
    invalid = [item for item in items if item not in available]
    if invalid:
        raise ValueError(f"{option_name} に未対応値があります: {invalid}")
    deduped: list[str] = []
    for item in items:
        if item not in deduped:
            deduped.append(item)
    return tuple(deduped)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="uc-rainfall-zip", description="UC Rainfall ZIP Flow CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="ZIP から 5日分のラスタ/グラフを生成する")
    run.add_argument("--base-date", required=True, help="基準日 (YYYY-MM-DD)")
    run.add_argument("--input-zipdir", default=r"outputs\uc_download\downloads")
    run.add_argument("--output-dir", default=r"outputs\uc_rainfall_zipflow")
    run.add_argument("--polygon-dir", default=r"data\大阪狭山市_流域界")
    run.add_argument("--enable-log", action="store_true")
    run.add_argument("--export-svg", action="store_true", help="グラフをSVGでも出力する（既定はPNGのみ）")
    run.add_argument("--style-profile", help="plots_ref に適用するスタイルプロファイル(JSON)")
    run.add_argument("--window-mode", choices=("offset", "range"), default="offset")
    run.add_argument("--days-before", type=int, default=2, help="window-mode=offset 時の基準日前日数")
    run.add_argument("--days-after", type=int, default=2, help="window-mode=offset 時の基準日後日数")
    run.add_argument("--start-date", help="window-mode=range 時の開始日 (YYYY-MM-DD)")
    run.add_argument("--end-date", help="window-mode=range 時の終了日 (YYYY-MM-DD)")
    run.add_argument(
        "--graph-spans",
        default="5d",
        help=f"plots_ref の出力期間（{', '.join(_AVAILABLE_GRAPH_SPANS)} のカンマ区切り）",
    )
    run.add_argument(
        "--ref-graph-kinds",
        default="sum,mean",
        help=f"plots_ref の指標（{', '.join(_AVAILABLE_REF_GRAPH_KINDS)} のカンマ区切り）",
    )
    run.add_argument(
        "--regions",
        default="nishiyoke_higashiyoke",
        help=f"出力対象 region_key のカンマ区切り ({', '.join(_AVAILABLE_REGIONS)})",
    )
    run.add_argument(
        "--outputs",
        default="raster,raster_bbox,plots",
        help=f"出力種別のカンマ区切り ({', '.join(_AVAILABLE_OUTPUTS)})",
    )

    style_gui = sub.add_parser("style-gui", help="グラフ体裁チューナーを起動する")
    style_gui.add_argument("--input-csv", help="*_timeseries.csv のパス（未指定時はサンプル表示）")
    style_gui.add_argument("--sample-mode", choices=("synthetic",), default="synthetic")
    style_gui.add_argument("--value-kind", choices=("sum", "mean"), default="mean")
    style_gui.add_argument("--preview-span", choices=("3d", "5d"), default="5d")
    style_gui.add_argument("--title", default="流域平均雨量（プレビュー）")
    style_gui.add_argument("--profile-path", help="初期読込するスタイルプロファイル(JSON)")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "style-gui":
        launch_style_tuner(
            input_csv=Path(args.input_csv) if args.input_csv else None,
            value_kind=args.value_kind,
            title=args.title,
            sample_mode=args.sample_mode,
            profile_path=Path(args.profile_path) if args.profile_path else None,
            preview_span=args.preview_span,
        )
        return
    if args.command != "run":
        parser.error(f"未対応コマンドです: {args.command}")

    try:
        regions = _parse_csv_choices(raw=args.regions, available=_AVAILABLE_REGIONS, option_name="--regions")
        outputs = _parse_csv_choices(raw=args.outputs, available=_AVAILABLE_OUTPUTS, option_name="--outputs")
        graph_spans = _parse_csv_choices(
            raw=args.graph_spans,
            available=_AVAILABLE_GRAPH_SPANS,
            option_name="--graph-spans",
        )
        ref_graph_kinds = _parse_csv_choices(
            raw=args.ref_graph_kinds,
            available=_AVAILABLE_REF_GRAPH_KINDS,
            option_name="--ref-graph-kinds",
        )
        config = RunConfig(
            base_date=_parse_base_date(args.base_date),
            input_zipdir=Path(args.input_zipdir),
            output_root=Path(args.output_dir),
            polygon_dir=Path(args.polygon_dir),
            enable_log=bool(args.enable_log),
            export_svg=bool(args.export_svg),
            window_mode=args.window_mode,
            days_before=int(args.days_before),
            days_after=int(args.days_after),
            start_date=_parse_optional_date(args.start_date),
            end_date=_parse_optional_date(args.end_date),
            graph_spans=graph_spans,
            ref_graph_kinds=ref_graph_kinds,
            style_profile_path=Path(args.style_profile) if args.style_profile else None,
            region_keys=regions,
            output_kinds=outputs,
        )
        result = run_zipflow(config)
        print(result["base_dir"])
    except ZipFlowError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(exc.exit_code) from exc
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
