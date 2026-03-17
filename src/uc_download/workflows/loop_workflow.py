from __future__ import annotations

import logging

from playwright.sync_api import Page

from ..models import BBox
from ..models import RequestWindow
from ..models import RunConfig
from ..pages import ParameterPage
from ..result_store import ResultStore
from .request_workflow import execute_request_flow


LOGGER = logging.getLogger(__name__)


def run_loop_flow(
    page: Page,
    *,
    windows: list[RequestWindow],
    config: RunConfig,
    store: ResultStore,
    expected_bbox: BBox,
    bbox_to_apply: BBox | None,
    retry_on_failure_count: int = 1,
    retry_wait_seconds: float = 10.0,
    skip_failed_window: bool = True,
) -> dict[str, object]:
    """複数期間の要求送信を順に実行し、サマリを返す。"""
    accepted_count = 0
    accepted_candidate_count = 0
    failed_count = 0
    processed_windows = 0
    retried_window_count = 0
    skipped_window_count = 0
    skipped_windows: list[dict[str, object]] = []
    last_successful_window: RequestWindow | None = None
    next_window: RequestWindow | None = None
    stopped_reason: str | None = None

    total_windows = len(windows)
    for index, window in enumerate(windows, start=1):
        processed_windows += 1
        max_attempts = 1 + max(0, retry_on_failure_count)
        final_result = None
        for attempt in range(1, max_attempts + 1):
            if attempt == 1:
                LOGGER.info("要求送信 %s/%s を開始します。window=%s", index, total_windows, window.label)
            else:
                retried_window_count += 1
                LOGGER.warning(
                    "要求送信を再試行します。window=%s attempt=%s/%s",
                    window.label,
                    attempt,
                    max_attempts,
                )
                try:
                    parameter_page = ParameterPage(page)
                    parameter_page.bring_to_front()
                    parameter_page.wait_until_ready(config.wait_for_page_ready_seconds)
                except Exception as exc:
                    final_result = None
                    stopped_reason = f"再試行前の画面復帰に失敗しました: {exc}"
                    LOGGER.exception("再試行前の画面復帰に失敗しました。window=%s", window.label)
                    break
                if retry_wait_seconds > 0:
                    page.wait_for_timeout(int(retry_wait_seconds * 1000))

            result = execute_request_flow(
                page,
                window=window,
                config=config,
                store=store,
                expected_bbox=expected_bbox,
                bbox_to_apply=bbox_to_apply,
            )
            store.append_request_result(result)
            final_result = result
            if not result.failed:
                break

        if final_result is None:
            failed_count += 1
            next_window = window
            if not stopped_reason:
                stopped_reason = "要求送信に失敗しました。"
            break

        if final_result.accepted:
            accepted_count += 1
        elif final_result.accepted_candidate:
            accepted_candidate_count += 1
        else:
            failed_count += 1
            if skip_failed_window:
                skipped_window_count += 1
                skipped_windows.append(
                    {
                        "window": window.to_dict(),
                        "message": final_result.message,
                    }
                )
                LOGGER.warning(
                    "この期間はスキップして続行します。window=%s message=%s",
                    window.label,
                    final_result.message,
                )
            else:
                next_window = window
                stopped_reason = final_result.message or "要求送信に失敗しました。"
                break

        if not final_result.failed:
            last_successful_window = window

        if index >= total_windows:
            continue

        next_window = windows[index]
        try:
            parameter_page = ParameterPage(page)
            parameter_page.bring_to_front()
            LOGGER.info("元画面の再利用可否を確認します。window=%s", window.label)
            parameter_page.wait_until_ready(config.wait_for_page_ready_seconds)
            if config.request_interval_seconds > 0:
                LOGGER.info(
                    "次期間へ進む前に %.1f 秒待機します。window=%s",
                    config.request_interval_seconds,
                    next_window.label,
                )
                page.wait_for_timeout(int(config.request_interval_seconds * 1000))
        except Exception as exc:
            stopped_reason = f"元画面の再利用確認に失敗しました: {exc}"
            LOGGER.exception("元画面の再利用確認に失敗しました。next_window=%s", next_window.label)
            failed_count += 1
            break

    completed_all = processed_windows == total_windows and stopped_reason is None
    return {
        "total_windows": total_windows,
        "processed_windows": processed_windows,
        "accepted_count": accepted_count,
        "accepted_candidate_count": accepted_candidate_count,
        "failed_count": failed_count,
        "retried_window_count": retried_window_count,
        "skipped_window_count": skipped_window_count,
        "skipped_windows": skipped_windows,
        "completed_all": completed_all,
        "last_successful_window": last_successful_window.to_dict() if last_successful_window else None,
        "next_window": next_window.to_dict() if next_window else None,
        "stopped_reason": stopped_reason,
    }
