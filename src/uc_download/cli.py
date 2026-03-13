from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from datetime import timedelta
from pathlib import Path

from .browser import open_browser_session
from .config import DEFAULT_BBOX_PAD_DEG
from .config import DEFAULT_BBOX_PRESET
from .config import DEFAULT_CHUNK_DAYS
from .config import DEFAULT_DOWNLOADS_DIR
from .config import DEFAULT_EMAIL
from .config import DEFAULT_OUTPUT_DIR
from .config import DEFAULT_PERIOD_END
from .config import DEFAULT_PERIOD_START
from .config import DEFAULT_REQUEST_INTERVAL_SECONDS
from .config import DEFAULT_WAIT_FOR_LOGIN_SECONDS
from .config import DEFAULT_WAIT_FOR_OK_SECONDS
from .config import DEFAULT_WAIT_FOR_PAGE_READY_SECONDS
from .config import PRESET_BBOXES
from .config import build_run_config
from .config import resolve_bbox
from .models import BBox
from .models import RunConfig
from .pages import ParameterPage
from .period_planner import build_request_windows
from .result_store import ResultStore
from .workflows import execute_request_flow
from .workflows import run_login_flow
from .workflows import run_loop_flow


LOGGER = logging.getLogger(__name__)


def _configure_logging() -> None:
    """CLI 実行時のログ出力設定を行う。"""
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


def _parse_date(value: str) -> date:
    """YYYY-MM-DD 形式の日付を解釈する。"""
    return date.fromisoformat(value)


def build_parser() -> argparse.ArgumentParser:
    """CLI 引数定義を構築する。"""
    parser = argparse.ArgumentParser(prog="uc-download", description="UC ダウンロード自動化 CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_plan = subparsers.add_parser("plan-periods", help="全期間を 3 日単位へ分割して保存する")
    p_plan.add_argument("--period-start", default=DEFAULT_PERIOD_START.isoformat())
    p_plan.add_argument("--period-end", default=DEFAULT_PERIOD_END.isoformat())
    p_plan.add_argument("--chunk-days", type=int, choices=[1, 2, 3], default=DEFAULT_CHUNK_DAYS)
    p_plan.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))

    p_single = subparsers.add_parser("login-and-request", help="ログインから 1 期間の要求送信までを実行する")
    _add_common_runtime_args(p_single)
    p_single.add_argument("--start-day", required=True)
    p_single.add_argument("--days", type=int, choices=[1, 2, 3], required=True)

    p_loop = subparsers.add_parser("loop-request-links", help="全期間に対して要求送信を繰り返す")
    _add_common_runtime_args(p_loop)
    p_loop.add_argument("--period-start", default=DEFAULT_PERIOD_START.isoformat())
    p_loop.add_argument("--period-end", default=DEFAULT_PERIOD_END.isoformat())
    p_loop.add_argument("--chunk-days", type=int, choices=[1, 2, 3], default=DEFAULT_CHUNK_DAYS)

    return parser


def _add_common_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--email", default=DEFAULT_EMAIL, help="ログインページへ入力するメールアドレス")
    parser.add_argument(
        "--bbox-mode",
        choices=["auto", "manual"],
        default="auto",
        help="bbox を自動入力するか、人手調整を使うか",
    )
    parser.add_argument(
        "--bbox-preset",
        choices=sorted(PRESET_BBOXES),
        default=DEFAULT_BBOX_PRESET,
        help="bbox プリセット名。省略時は大和川流域を使う",
    )
    parser.add_argument(
        "--bbox-pad-deg",
        type=float,
        default=DEFAULT_BBOX_PAD_DEG,
        help="bbox またはプリセットへ足す余白量（度）",
    )
    parser.add_argument(
        "--bbox",
        type=float,
        nargs=4,
        metavar=("SOUTH", "NORTH", "WEST", "EAST"),
        help="bbox を直接指定するときに使う",
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="実行結果ファイルの出力先")
    parser.add_argument("--downloads-dir", default=str(DEFAULT_DOWNLOADS_DIR), help="将来の ZIP 保存先")
    parser.add_argument("--headless", action="store_true", help="headless Chromium で実行する")
    parser.add_argument("--pause", action="store_true", help="終了前に Enter 入力までブラウザを閉じない")
    parser.add_argument(
        "--wait-for-login-seconds",
        type=float,
        default=DEFAULT_WAIT_FOR_LOGIN_SECONDS,
        help="OTP 完了後にパラメータ画面が出るまで待つ秒数",
    )
    parser.add_argument(
        "--wait-for-ok-seconds",
        type=float,
        default=DEFAULT_WAIT_FOR_OK_SECONDS,
        help="変換開始後に OK や dialog を監視する秒数",
    )
    parser.add_argument(
        "--wait-for-page-ready-seconds",
        type=float,
        default=DEFAULT_WAIT_FOR_PAGE_READY_SECONDS,
        help="元画面の再利用可否を確認する待機秒数",
    )
    parser.add_argument(
        "--request-interval-seconds",
        type=float,
        default=DEFAULT_REQUEST_INTERVAL_SECONDS,
        help="各期間要求の間に入れる待機秒数",
    )


def main() -> int:
    """CLI エントリポイント。"""
    _configure_logging()
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "plan-periods":
        windows = build_request_windows(
            start_date=_parse_date(args.period_start),
            end_date=_parse_date(args.period_end),
            chunk_days=args.chunk_days,
        )
        store = ResultStore(Path(args.output_dir))
        path = store.save_period_plan(windows)
        LOGGER.info("期間計画を保存しました。件数=%s path=%s", len(windows), path)
        print(path)
        return 0

    bbox = resolve_bbox(
        explicit_bbox=tuple(args.bbox) if args.bbox else None,
        preset_name=args.bbox_preset,
        pad_deg=args.bbox_pad_deg,
    )
    config = build_run_config(
        email=args.email,
        bbox_mode=args.bbox_mode,
        bbox=bbox,
        output_dir=Path(args.output_dir),
        downloads_dir=Path(args.downloads_dir),
        headless=args.headless,
        wait_for_login_seconds=args.wait_for_login_seconds,
        wait_for_ok_seconds=args.wait_for_ok_seconds,
        wait_for_page_ready_seconds=args.wait_for_page_ready_seconds,
        request_interval_seconds=args.request_interval_seconds,
    )
    store = ResultStore(config.output_dir)

    if args.command == "login-and-request":
        start_date = _parse_date(args.start_day)
        end_date = start_date + timedelta(days=args.days - 1)
        window = build_request_windows(
            start_date=start_date,
            end_date=end_date,
            chunk_days=args.days,
        )[0]
        store.save_run_config(config, command=args.command)
        store.save_period_plan([window])

        with open_browser_session(config) as session:
            try:
                parameter_page = run_login_flow(session.page, config)
                runtime_bbox, bbox_to_apply = _prepare_runtime_bbox(parameter_page, config, store)
                result = execute_request_flow(
                    session.page,
                    window=window,
                    config=config,
                    store=store,
                    expected_bbox=runtime_bbox,
                    bbox_to_apply=bbox_to_apply,
                )
                store.append_request_result(result)
                summary = {
                    "command": args.command,
                    "bbox_mode": config.bbox_mode,
                    "runtime_bbox": runtime_bbox.to_dict(),
                    "completed_all": not result.failed,
                    "accepted_count": 1 if result.accepted else 0,
                    "accepted_candidate_count": 1 if result.accepted_candidate else 0,
                    "failed_count": 1 if result.failed else 0,
                    "last_successful_window": result.window.to_dict() if not result.failed else None,
                    "next_window": None,
                    "stopped_reason": result.message,
                }
                store.save_summary(summary)
                if args.pause:
                    _pause_browser_if_needed(session.page, "単発実行が終わりました。ブラウザを確認したら Enter を押してください。")
            except Exception:
                if args.pause:
                    _pause_browser_if_needed(session.page, "エラーで停止しました。ブラウザを確認したら Enter を押してください。")
                raise

        LOGGER.info("単発要求の実行が完了しました。status=%s", result.status)
        print(store.run_summary_path)
        return 0 if not result.failed else 1

    if args.command == "loop-request-links":
        windows = build_request_windows(
            start_date=_parse_date(args.period_start),
            end_date=_parse_date(args.period_end),
            chunk_days=args.chunk_days,
        )
        store.save_run_config(config, command=args.command)
        store.save_period_plan(windows)

        with open_browser_session(config) as session:
            try:
                parameter_page = run_login_flow(session.page, config)
                runtime_bbox, bbox_to_apply = _prepare_runtime_bbox(parameter_page, config, store)
                summary = run_loop_flow(
                    session.page,
                    windows=windows,
                    config=config,
                    store=store,
                    expected_bbox=runtime_bbox,
                    bbox_to_apply=bbox_to_apply,
                )
                summary["command"] = args.command
                summary["bbox_mode"] = config.bbox_mode
                summary["runtime_bbox"] = runtime_bbox.to_dict()
                store.save_summary(summary)
                if args.pause:
                    _pause_browser_if_needed(session.page, "連続送信が終わりました。ブラウザを確認したら Enter を押してください。")
            except Exception:
                if args.pause:
                    _pause_browser_if_needed(session.page, "エラーで停止しました。ブラウザを確認したら Enter を押してください。")
                raise

        LOGGER.info(
            "連続送信の実行が完了しました。processed=%s accepted=%s accepted_candidate=%s failed=%s",
            summary["processed_windows"],
            summary["accepted_count"],
            summary["accepted_candidate_count"],
            summary["failed_count"],
        )
        print(store.run_summary_path)
        return 0 if bool(summary["completed_all"]) else 1

    parser.error(f"不明なコマンドです: {args.command}")
    return 2


def _prepare_runtime_bbox(
    parameter_page: ParameterPage,
    config: RunConfig,
    store: ResultStore,
) -> tuple[BBox, BBox | None]:
    """今回の実行で使う bbox を確定する。"""
    if config.bbox_mode == "auto":
        LOGGER.info("bbox 自動モードを使用します。bbox=%s", config.bbox.to_dict())
        return config.bbox, config.bbox

    if not sys.stdin.isatty():
        raise RuntimeError("bbox 手動モードは対話端末でのみ利用できます。")

    LOGGER.info(
        "bbox 手動モードです。地図ハンドルで範囲を調整してください。目標 bbox=%s",
        config.bbox.to_dict(),
    )
    input("ブラウザで bbox を調整したら Enter を押してください。")
    manual_bbox = parameter_page.read_bbox()
    if manual_bbox is None:
        raise RuntimeError("手動調整後の bbox を読み取れませんでした。")
    screenshot = store.save_screenshot(parameter_page.page, "manual_bbox_confirmed")
    if screenshot is not None:
        LOGGER.info("手動調整後のスクリーンショットを保存しました。path=%s", screenshot)
    LOGGER.info("手動で確定した bbox を採用します。bbox=%s", manual_bbox.to_dict())
    return manual_bbox, None


def _pause_browser_if_needed(page, message: str) -> None:
    """必要なときだけブラウザを開いたまま停止する。"""
    if not sys.stdin.isatty():
        return
    try:
        if page.is_closed():
            return
    except Exception:
        return
    input(message)


if __name__ == "__main__":
    raise SystemExit(main())
