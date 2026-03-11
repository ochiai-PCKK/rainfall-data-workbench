from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

from .db import initialize_schema, open_db
from .services import generate_metric_event_charts, ingest_uc_rainfall, list_candidate_cells


def _configure_logging() -> None:
    """CLI 実行時のログ出力設定を行う。"""
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


def _parse_datetime(value: str) -> datetime:
    """`YYYY-MM-DDTHH:MM:SS` 形式の日時文字列を JST 前提で解釈する。"""
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")


def build_parser() -> argparse.ArgumentParser:
    """UC 降雨処理 CLI の引数定義を構築する。"""
    parser = argparse.ArgumentParser(prog="uc-rainfall", description="UC 降雨処理 CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_init = subparsers.add_parser("init-db", help="SQLite スキーマを初期化する")
    p_init.add_argument("--db-path", required=True)

    p_ingest = subparsers.add_parser("ingest", help="UC-tools データを DB へ取り込む")
    p_ingest.add_argument("--db-path", required=True)
    p_ingest.add_argument(
        "--input-path",
        "--input-dir",
        dest="input_path",
        required=True,
        help="展開済みディレクトリまたは ZIP ファイルのパス",
    )
    p_ingest.add_argument("--polygon-dir", required=True)
    p_ingest.add_argument("--dataset-id")
    p_ingest.add_argument("--grid-crs", default="EPSG:4326")

    p_list = subparsers.add_parser("list-cells", help="候補セル一覧を表示する")
    p_list.add_argument("--db-path", required=True)
    p_list.add_argument("--dataset-id", required=True)
    p_list.add_argument("--polygon-name")

    p_plot = subparsers.add_parser("plot", help="イベントグラフを出力する")
    p_plot.add_argument("--db-path", required=True)
    p_plot.add_argument("--dataset-id", required=True)
    p_plot.add_argument("--polygon-name", required=True)
    p_plot.add_argument("--row", type=int)
    p_plot.add_argument("--col", type=int)
    p_plot.add_argument(
        "--series-mode",
        choices=["cell", "polygon_sum", "polygon_mean"],
        default="cell",
        help="グラフ化する系列の範囲",
    )
    p_plot.add_argument("--view-start", required=True)
    p_plot.add_argument("--view-end", required=True)
    p_plot.add_argument("--out-dir", required=True)
    return parser


def main() -> None:
    """CLI エントリポイント。"""
    _configure_logging()
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "init-db":
        with open_db(args.db_path) as conn:
            initialize_schema(conn)
        print(Path(args.db_path))
        return

    if args.command == "ingest":
        ingest_uc_rainfall(
            db_path=args.db_path,
            input_path=args.input_path,
            polygon_dir=args.polygon_dir,
            dataset_id=args.dataset_id,
            grid_crs=args.grid_crs,
        )
        print(Path(args.db_path))
        return

    if args.command == "list-cells":
        frame = list_candidate_cells(
            db_path=args.db_path,
            dataset_id=args.dataset_id,
            polygon_name=args.polygon_name,
        )
        if frame.empty:
            print("候補セルは見つかりませんでした。")
        else:
            display = frame.rename(
                columns={
                    "polygon_name": "流域名",
                    "row": "行",
                    "col": "列",
                    "x_center": "中心X",
                    "y_center": "中心Y",
                    "inside_flag": "内包",
                }
            )
            print(display.to_string(index=False))
        return

    if args.command == "plot":
        paths = generate_metric_event_charts(
            db_path=args.db_path,
            dataset_id=args.dataset_id,
            polygon_name=args.polygon_name,
            row=args.row,
            col=args.col,
            series_mode=args.series_mode,
            view_start=_parse_datetime(args.view_start),
            view_end=_parse_datetime(args.view_end),
            out_dir=args.out_dir,
        )
        for path in paths:
            print(path)
        return

    parser.error(f"不明なコマンドです: {args.command}")


if __name__ == "__main__":
    main()
