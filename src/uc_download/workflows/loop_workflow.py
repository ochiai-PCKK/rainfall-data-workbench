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
) -> dict[str, object]:
    """複数期間の要求送信を順に実行し、サマリを返す。"""
    accepted_count = 0
    accepted_candidate_count = 0
    failed_count = 0
    processed_windows = 0
    last_successful_window: RequestWindow | None = None
    next_window: RequestWindow | None = None
    stopped_reason: str | None = None

    total_windows = len(windows)
    for index, window in enumerate(windows, start=1):
        LOGGER.info("要求送信 %s/%s を開始します。window=%s", index, total_windows, window.label)
        result = execute_request_flow(
            page,
            window=window,
            config=config,
            store=store,
            expected_bbox=expected_bbox,
            bbox_to_apply=bbox_to_apply,
        )
        store.append_request_result(result)
        processed_windows += 1

        if result.accepted:
            accepted_count += 1
        elif result.accepted_candidate:
            accepted_candidate_count += 1
        else:
            failed_count += 1
            next_window = window
            stopped_reason = result.message or "要求送信に失敗しました。"
            break

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

    completed_all = processed_windows == total_windows and failed_count == 0
    return {
        "total_windows": total_windows,
        "processed_windows": processed_windows,
        "accepted_count": accepted_count,
        "accepted_candidate_count": accepted_candidate_count,
        "failed_count": failed_count,
        "completed_all": completed_all,
        "last_successful_window": last_successful_window.to_dict() if last_successful_window else None,
        "next_window": next_window.to_dict() if next_window else None,
        "stopped_reason": stopped_reason,
    }
