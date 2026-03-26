from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from .application import run_zipflow
from .benchmark_engine import run_core_benchmark
from .errors import ZipFlowError
from .excel_application import export_excel_event_candidates_csv
from .gui.app import launch_zipflow_gui, launch_zipflow_gui_with_capture
from .gui.style_tuner_window import launch_style_tuner
from .models import RunConfig

_AVAILABLE_REGIONS = ("nishiyoke", "higashiyoke", "nishiyoke_higashiyoke", "yamatogawa")
_AVAILABLE_OUTPUTS = ("raster", "raster_bbox", "plots", "plots_ref", "analysis_csv", "timeseries_csv")
_AVAILABLE_OUTPUTS_DISPLAY = ("raster", "raster_bbox", "plots", "plots_ref", "analysis_csv")
_AVAILABLE_GRAPH_SPANS = ("3d", "5d")
_AVAILABLE_REF_GRAPH_KINDS = ("sum", "mean")
_AVAILABLE_CONFLICT_POLICIES = ("rename", "overwrite", "cancel")
_AVAILABLE_ENGINES = ("python", "rust_pyo3")


def _parse_base_date(value: str):
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_optional_date(value: str | None):
    if value is None:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_dev_mode(value: str | None) -> bool | None:
    if value is None:
        return None
    raw = value.strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"--dev-mode は 1/0 (または true/false) を指定してください: {value}")


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


def _normalize_outputs(outputs: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for item in outputs:
        mapped = "timeseries_csv" if item == "analysis_csv" else item
        if mapped not in normalized:
            normalized.append(mapped)
    return tuple(normalized)


def _build_excel_candidates_output_paths(*, input_excel: Path, output_dir: Path) -> tuple[Path, Path]:
    stem = input_excel.stem
    return (
        output_dir / f"{stem}_候補日付リスト.csv",
        output_dir / f"{stem}_候補日付一覧_unique.csv",
    )


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
    run.add_argument(
        "--on-conflict",
        choices=_AVAILABLE_CONFLICT_POLICIES,
        default="rename",
        help="出力ファイル衝突時の挙動 (rename|overwrite|cancel)",
    )
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
        default="raster,raster_bbox,plots_ref",
        help=(
            f"出力種別のカンマ区切り ({', '.join(_AVAILABLE_OUTPUTS_DISPLAY)}) "
            "※timeseries_csv も互換指定可"
        ),
    )
    run.add_argument(
        "--engine",
        choices=_AVAILABLE_ENGINES,
        default="python",
        help="計算エンジンを選択する",
    )

    style_gui = sub.add_parser("style-gui", help="グラフスタイル調整を起動する")
    style_gui.add_argument("--input-csv", help="*_timeseries.csv のパス（未指定時はサンプル表示）")
    style_gui.add_argument("--sample-mode", choices=("synthetic",), default="synthetic")
    style_gui.add_argument("--value-kind", choices=("sum", "mean"), default="mean")
    style_gui.add_argument("--preview-span", choices=("3d", "5d"), default="5d")
    style_gui.add_argument("--title", default="流域平均雨量（プレビュー）")
    style_gui.add_argument("--profile-path", help="初期読込するスタイルプロファイル(JSON)")

    gui = sub.add_parser("gui", help="流域雨量グラフ GUI を起動する")
    gui.add_argument(
        "--auto-capture-seconds",
        type=float,
        help="起動後に自動でスクリーンショット保存する秒数（例: 1.5）",
    )
    gui.add_argument(
        "--auto-exit-after-capture",
        action="store_true",
        help="自動スクリーンショット保存後にGUIを終了する",
    )
    gui.add_argument(
        "--test-mode",
        action="store_true",
        help="起動テストを実行してスクリーンショット/JSONを保存後に自動終了する",
    )
    gui.add_argument(
        "--dev-mode",
        help="開発者ツールを表示するか (1/0, true/false)。未指定時は環境変数 UC_ZIPFLOW_DEV_UI に従う",
    )

    excel_candidates = sub.add_parser(
        "excel-candidates",
        help="Excelシート名からイベント候補日付CSVを2点（詳細/重複除去）出力する",
    )
    excel_candidates.add_argument("--input-excel", required=True, help="入力Excelファイル(.xlsx/.xls)")
    excel_candidates.add_argument("--output-dir", default=r"outputs\excel_candidates", help="CSV出力先ディレクトリ")

    benchmark = sub.add_parser("benchmark", help="Python/Rust の集計コアを比較ベンチマークする")
    benchmark.add_argument("--repeat", type=int, default=3, help="計測反復回数")
    benchmark.add_argument("--warmup", type=int, default=1, help="ウォームアップ回数")
    benchmark.add_argument("--seed", type=int, default=42, help="乱数シード")
    benchmark.add_argument("--slots", type=int, default=120, help="時系列点数")
    benchmark.add_argument("--rows", type=int, default=64, help="格子行数")
    benchmark.add_argument("--cols", type=int, default=64, help="格子列数")
    benchmark.add_argument(
        "--output-dir",
        default=r"outputs\uc_rainfall_zipflow\benchmarks",
        help="ベンチ結果の出力先ディレクトリ",
    )
    benchmark.add_argument(
        "--rust-manifest",
        default=r"rust\weighted_core\Cargo.toml",
        help="Rustベンチ実行用Cargo.tomlのパス",
    )
    benchmark.add_argument(
        "--rebuild-rust",
        action="store_true",
        help="Rustバイナリを強制再ビルドする（既定はキャッシュ再利用）",
    )
    benchmark.add_argument(
        "--use-pyo3",
        action="store_true",
        help="PyO3エンジン（同一プロセス）も比較対象に含める",
    )
    benchmark.add_argument(
        "--pyo3-manifest",
        default=r"rust\weighted_core_pyo3\Cargo.toml",
        help="PyO3拡張のCargo.tomlパス",
    )
    benchmark.add_argument(
        "--rebuild-pyo3",
        action="store_true",
        help="PyO3拡張を強制再ビルドする",
    )
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
    if args.command == "gui":
        try:
            dev_mode = _parse_dev_mode(args.dev_mode)
        except ValueError as exc:
            parser.error(str(exc))
        if args.test_mode:
            launch_zipflow_gui_with_capture(
                auto_capture_seconds=None,
                auto_exit_after_capture=True,
                test_mode=True,
                dev_mode=dev_mode,
            )
        elif args.auto_capture_seconds is None:
            launch_zipflow_gui(dev_mode=dev_mode)
        else:
            launch_zipflow_gui_with_capture(
                auto_capture_seconds=float(args.auto_capture_seconds),
                auto_exit_after_capture=bool(args.auto_exit_after_capture),
                test_mode=False,
                dev_mode=dev_mode,
            )
        return
    if args.command == "excel-candidates":
        try:
            input_excel = Path(args.input_excel)
            output_dir = Path(args.output_dir)
            output_all_csv, output_unique_csv = _build_excel_candidates_output_paths(
                input_excel=input_excel,
                output_dir=output_dir,
            )
            result = export_excel_event_candidates_csv(
                input_excel=input_excel,
                output_all_csv=output_all_csv,
                output_unique_csv=output_unique_csv,
            )
            print(result["output_all_csv"])
            print(result["output_unique_csv"])
            print(
                f"candidate_count={result['candidate_count']} "
                f"unique_date_count={result['unique_date_count']}"
            )
        except ZipFlowError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            raise SystemExit(exc.exit_code) from exc
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        return
    if args.command == "benchmark":
        try:
            result = run_core_benchmark(
                output_root=Path(args.output_dir),
                repeat=int(args.repeat),
                warmup=int(args.warmup),
                seed=int(args.seed),
                slots=int(args.slots),
                rows=int(args.rows),
                cols=int(args.cols),
                rust_manifest=Path(args.rust_manifest),
                force_rebuild=bool(args.rebuild_rust),
                pyo3_manifest=Path(args.pyo3_manifest),
                enable_pyo3=bool(args.use_pyo3),
                force_rebuild_pyo3=bool(args.rebuild_pyo3),
            )
            print(result["output_dir"])
            summary = cast(dict[str, Any], result["summary"])
            line = (
                "speed_score={:.4f} memory_score={:.4f} total_score={:.4f} accuracy_passed={}".format(
                    summary["speed_score"],
                    summary["memory_score"],
                    summary["total_score"],
                    summary["accuracy"]["passed"],
                )
            )
            if summary.get("rust_pyo3"):
                pyo3 = cast(dict[str, Any], summary["rust_pyo3"])
                line += (
                    " | pyo3_speed_score={:.4f} pyo3_memory_score={:.4f} "
                    "pyo3_total_score={:.4f} pyo3_accuracy_passed={}"
                ).format(
                    pyo3["speed_score"],
                    pyo3["memory_score"],
                    pyo3["total_score"],
                    pyo3["accuracy"]["passed"],
                )
            print(line)
        except ZipFlowError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            raise SystemExit(exc.exit_code) from exc
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        return
    if args.command != "run":
        parser.error(f"未対応コマンドです: {args.command}")

    try:
        regions = _parse_csv_choices(raw=args.regions, available=_AVAILABLE_REGIONS, option_name="--regions")
        outputs = _parse_csv_choices(raw=args.outputs, available=_AVAILABLE_OUTPUTS, option_name="--outputs")
        outputs = _normalize_outputs(outputs)
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
            on_conflict=args.on_conflict,
            engine=args.engine,
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
