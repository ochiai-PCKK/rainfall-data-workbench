from __future__ import annotations

import argparse
import logging
import re
from datetime import datetime
from pathlib import Path

from .db import initialize_schema, open_db
from .services import generate_metric_event_charts, ingest_uc_rainfall, ingest_uc_rainfall_many, list_candidate_cells
from .settings_store import load_settings, update_settings


def _configure_logging() -> None:
    """CLI 実行時のログ出力設定を行う。"""
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


def _parse_datetime(value: str) -> datetime:
    """`YYYY-MM-DDTHH:MM:SS` 形式の日時文字列を JST 前提で解釈する。"""
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")


def _parse_yyyymmdd(value: str) -> datetime:
    """`YYYYMMDD` 形式の日付文字列を解釈する。"""
    return datetime.strptime(value, "%Y%m%d")


def _extract_head_date(name: str) -> str | None:
    """ファイル名先頭の日付8桁を返す。見つからない場合は `None`。"""
    match = re.match(r"^(\d{8})", name)
    return match.group(1) if match else None


def _collect_zip_paths(
    *,
    zipdir: str,
    from_date: str | None,
    to_date: str | None,
) -> list[str]:
    """ZIP ディレクトリから対象ファイル一覧を収集する。"""
    base = Path(zipdir)
    if not base.exists():
        raise FileNotFoundError(f"ZIPディレクトリが見つかりません: {zipdir}")
    if not base.is_dir():
        raise NotADirectoryError(f"ZIPディレクトリではありません: {zipdir}")

    from_key = _parse_yyyymmdd(from_date).strftime("%Y%m%d") if from_date else None
    to_key = _parse_yyyymmdd(to_date).strftime("%Y%m%d") if to_date else None

    paths: list[str] = []
    for path in sorted(base.glob("*.zip"), key=lambda p: p.name):
        date_key = _extract_head_date(path.name)
        if date_key is None:
            continue
        if from_key is not None and date_key < from_key:
            continue
        if to_key is not None and date_key > to_key:
            continue
        paths.append(str(path))
    return paths


def build_parser() -> argparse.ArgumentParser:
    """UC 降雨処理 CLI の引数定義を構築する。"""
    cached = load_settings()
    parser = argparse.ArgumentParser(prog="uc-rainfall", description="UC 降雨処理 CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_init = subparsers.add_parser("init-db", help="SQLite スキーマを初期化する")
    p_init.add_argument("--db-path", default=cached.get("db_path"))

    p_ingest = subparsers.add_parser("ingest", help="UC-tools データを DB へ取り込む")
    p_ingest.add_argument("--db-path", default=cached.get("db_path"))
    p_ingest.add_argument(
        "--input-path",
        "--input-dir",
        dest="input_paths",
        action="append",
        help="展開済みディレクトリまたは ZIP ファイルのパス。複数指定可",
    )
    p_ingest.add_argument(
        "--input-zipdir",
        help="ZIP ファイル群を格納したディレクトリ。--input-path とは排他",
    )
    p_ingest.add_argument(
        "--from-date",
        help="ZIP ファイル名先頭8桁の日付で下限を指定する（YYYYMMDD）",
    )
    p_ingest.add_argument(
        "--to-date",
        help="ZIP ファイル名先頭8桁の日付で上限を指定する（YYYYMMDD）",
    )
    p_ingest.add_argument(
        "--dry-run",
        action="store_true",
        help="取り込みはせず、対象ZIPのみ表示する",
    )
    p_ingest.add_argument(
        "--polygon-dir",
        default=cached.get("polygon_dir"),
        help="ポリゴンディレクトリ。省略時は DB 登録済みポリゴンを使う",
    )
    p_ingest.add_argument("--dataset-id")
    p_ingest.add_argument("--grid-crs", default="EPSG:4326")

    p_list = subparsers.add_parser("list-cells", help="候補セル一覧を表示する")
    p_list.add_argument("--db-path", default=cached.get("db_path"))
    p_list.add_argument("--dataset-id")
    p_list.add_argument("--polygon-name")

    p_plot = subparsers.add_parser("plot", help="イベントグラフを出力する")
    p_plot.add_argument("--db-path", default=cached.get("db_path"))
    p_plot.add_argument("--dataset-id")
    p_plot.add_argument("--polygon-name", default=cached.get("polygon_name"))
    p_plot.add_argument("--row", type=int)
    p_plot.add_argument("--col", type=int)
    p_plot.add_argument("--local-row", type=int)
    p_plot.add_argument("--local-col", type=int)
    p_plot.add_argument(
        "--series-mode",
        choices=["cell", "polygon_sum", "polygon_mean", "polygon_weighted_sum", "polygon_weighted_mean"],
        default=cached.get("series_mode", "cell"),
        help="グラフ化する系列の範囲",
    )
    p_plot.add_argument("--view-start", default=cached.get("view_start"))
    p_plot.add_argument("--view-end", default=cached.get("view_end"))
    p_plot.add_argument("--out-dir", default=cached.get("out_dir"))

    p_gui = subparsers.add_parser("gui", help="Tkinter GUI を起動する")
    p_gui.add_argument("--test-mode", action="store_true", help="AI テストモードで起動する")
    return parser


def _require_value(parser: argparse.ArgumentParser, value: str | None, option_name: str) -> str:
    """必須値が未設定のときに parser error を出す。"""
    if value:
        return value
    parser.error(f"{option_name} を指定してください。設定キャッシュにも見つかりません。")
    raise AssertionError("unreachable")


def main() -> None:
    """CLI エントリポイント。"""
    _configure_logging()
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "init-db":
        args.db_path = _require_value(parser, args.db_path, "--db-path")
        with open_db(args.db_path) as conn:
            initialize_schema(conn)
        update_settings(db_path=args.db_path)
        print(Path(args.db_path))
        return

    if args.command == "ingest":
        args.db_path = _require_value(parser, args.db_path, "--db-path")
        input_paths: list[str | Path] = [Path(path) for path in (args.input_paths or [])]
        if args.input_zipdir and input_paths:
            parser.error("--input-zipdir と --input-path は同時に指定できません。")
        if args.input_zipdir:
            input_paths = [
                Path(path)
                for path in _collect_zip_paths(
                zipdir=args.input_zipdir,
                from_date=args.from_date,
                to_date=args.to_date,
                )
            ]
        if not input_paths:
            parser.error("取り込み対象がありません。--input-path または --input-zipdir を指定してください。")

        if args.dry_run:
            for input_path in input_paths:
                print(input_path)
            return

        if len(input_paths) == 1:
            ingest_uc_rainfall(
                db_path=args.db_path,
                input_path=input_paths[0],
                polygon_dir=args.polygon_dir,
                dataset_id=args.dataset_id,
                grid_crs=args.grid_crs,
            )
        else:
            if args.dataset_id:
                parser.error(
                    "複数入力のときは --dataset-id を指定できません。"
                    "各入力から自動で dataset_id を決定します。"
                )
            ingest_uc_rainfall_many(
                db_path=args.db_path,
                input_paths=input_paths,
                polygon_dir=args.polygon_dir,
                grid_crs=args.grid_crs,
            )
        update_settings(
            db_path=args.db_path,
            polygon_dir=args.polygon_dir,
            input_paths=[str(path) for path in input_paths],
        )
        print(Path(args.db_path))
        return

    if args.command == "list-cells":
        args.db_path = _require_value(parser, args.db_path, "--db-path")
        frame = list_candidate_cells(
            db_path=args.db_path,
            dataset_id=args.dataset_id,
            polygon_name=args.polygon_name,
        )
        update_settings(db_path=args.db_path, polygon_name=args.polygon_name, dataset_id=args.dataset_id)
        if frame.empty:
            print("候補セルは見つかりませんでした。")
        else:
            display = frame.rename(
                columns={
                    "polygon_name": "流域名",
                    "polygon_local_row": "流域内行",
                    "polygon_local_col": "流域内列",
                    "x_center": "中心X",
                    "y_center": "中心Y",
                    "overlap_ratio": "重なり率",
                    "inside_flag": "内包",
                    "dataset_count": "データセット数",
                }
            )
            print(display.to_string(index=False))
        return

    if args.command == "plot":
        args.db_path = _require_value(parser, args.db_path, "--db-path")
        args.polygon_name = _require_value(parser, args.polygon_name, "--polygon-name")
        args.view_start = _require_value(parser, args.view_start, "--view-start")
        args.view_end = _require_value(parser, args.view_end, "--view-end")
        args.out_dir = _require_value(parser, args.out_dir, "--out-dir")
        paths = generate_metric_event_charts(
            db_path=args.db_path,
            dataset_id=args.dataset_id,
            polygon_name=args.polygon_name,
            row=args.row,
            col=args.col,
            local_row=args.local_row,
            local_col=args.local_col,
            series_mode=args.series_mode,
            view_start=_parse_datetime(args.view_start),
            view_end=_parse_datetime(args.view_end),
            out_dir=args.out_dir,
        )
        update_settings(
            db_path=args.db_path,
            polygon_name=args.polygon_name,
            dataset_id=args.dataset_id,
            series_mode=args.series_mode,
            view_start=args.view_start,
            view_end=args.view_end,
            out_dir=args.out_dir,
            local_row=args.local_row,
            local_col=args.local_col,
        )
        for path in paths:
            print(path)
        return

    if args.command == "gui":
        from .gui import run_gui

        run_gui(test_mode=bool(args.test_mode))
        return

    parser.error(f"不明なコマンドです: {args.command}")


if __name__ == "__main__":
    main()
