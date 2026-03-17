from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .application import run_zipflow
from .errors import ZipFlowError
from .models import RunConfig

_AVAILABLE_REGIONS = ("nishiyoke", "higashiyoke", "nishiyoke_higashiyoke", "yamatogawa")
_AVAILABLE_OUTPUTS = ("raster", "raster_bbox", "plots", "plots_ref", "timeseries_csv")


def _parse_base_date(value: str):
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
    run.add_argument(
        "--regions",
        default=",".join(_AVAILABLE_REGIONS),
        help=f"出力対象 region_key のカンマ区切り ({', '.join(_AVAILABLE_REGIONS)})",
    )
    run.add_argument(
        "--outputs",
        default="raster,raster_bbox,plots",
        help=f"出力種別のカンマ区切り ({', '.join(_AVAILABLE_OUTPUTS)})",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command != "run":
        parser.error(f"未対応コマンドです: {args.command}")

    try:
        regions = _parse_csv_choices(raw=args.regions, available=_AVAILABLE_REGIONS, option_name="--regions")
        outputs = _parse_csv_choices(raw=args.outputs, available=_AVAILABLE_OUTPUTS, option_name="--outputs")
        config = RunConfig(
            base_date=_parse_base_date(args.base_date),
            input_zipdir=Path(args.input_zipdir),
            output_root=Path(args.output_dir),
            polygon_dir=Path(args.polygon_dir),
            enable_log=bool(args.enable_log),
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
