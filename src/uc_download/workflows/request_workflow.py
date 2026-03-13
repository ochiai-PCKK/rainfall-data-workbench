from __future__ import annotations

import logging
from datetime import datetime

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from ..models import RequestResult
from ..models import RequestWindow
from ..models import RunConfig
from ..models import BBox
from ..pages import ConfirmPage
from ..pages import ParameterPage
from ..result_store import ResultStore


LOGGER = logging.getLogger(__name__)
_BBOX_TOLERANCE = 1e-6


def execute_request_flow(
    page: Page,
    *,
    window: RequestWindow,
    config: RunConfig,
    store: ResultStore,
    expected_bbox: BBox,
    bbox_to_apply: BBox | None = None,
) -> RequestResult:
    """1 期間ぶんのリンク送信要求を実行して結果を返す。"""
    started_at = datetime.now()
    screenshot_paths: list = []
    parameter_page_detected = False
    confirm_page_detected = False
    parameter_bbox: dict[str, float] | None = None
    confirm_bbox: dict[str, float] | None = None
    dialog_seen = False
    ok_clicked = False
    confirm_tab_closed = False
    final_url: str | None = None
    message: str | None = None
    confirm_popup: Page | None = None

    try:
        parameter_page = ParameterPage(page)
        parameter_page.wait_until_ready(config.wait_for_page_ready_seconds)
        parameter_page_detected = True

        LOGGER.info("期間設定を開始します。window=%s", window.label)
        parameter_page.set_start_day(window.start_date.isoformat())
        parameter_page.set_days(window.days)
        if bbox_to_apply is not None:
            parameter_page.set_bbox(bbox_to_apply)
        actual_parameter_bbox = parameter_page.read_bbox()
        if actual_parameter_bbox is None:
            raise RuntimeError("パラメータ画面から bbox 値を読み取れませんでした。")
        parameter_bbox = actual_parameter_bbox.to_dict()
        if not actual_parameter_bbox.is_close(expected_bbox, tolerance=_BBOX_TOLERANCE):
            raise RuntimeError(
                "パラメータ画面の bbox が期待値と一致しません。"
                f" expected={expected_bbox.to_dict()} actual={parameter_bbox}"
            )
        LOGGER.info("パラメータ画面の bbox 反映を確認しました。window=%s bbox=%s", window.label, parameter_bbox)

        parameter_shot = store.save_screenshot(page, f"{window.label}_parameter")
        if parameter_shot is not None:
            screenshot_paths.append(parameter_shot)

        confirm_popup = parameter_page.open_confirm_popup()
        confirm_page = ConfirmPage(confirm_popup)
        confirm_page.wait_until_ready()
        confirm_page_detected = True
        final_url = _safe_page_url(confirm_popup)
        LOGGER.info("確認画面を取得しました。window=%s url=%s", window.label, final_url)
        actual_confirm_bbox = confirm_page.read_bbox()
        if actual_confirm_bbox is None:
            raise RuntimeError("確認画面から bbox 値を読み取れませんでした。")
        confirm_bbox = actual_confirm_bbox.to_dict()
        if not actual_confirm_bbox.is_close(expected_bbox, tolerance=_BBOX_TOLERANCE):
            raise RuntimeError(
                "確認画面の bbox が期待値と一致しません。"
                f" expected={expected_bbox.to_dict()} actual={confirm_bbox}"
            )
        LOGGER.info("確認画面の bbox 反映を確認しました。window=%s bbox=%s", window.label, confirm_bbox)

        confirm_shot = store.save_screenshot(confirm_popup, f"{window.label}_confirm")
        if confirm_shot is not None:
            screenshot_paths.append(confirm_shot)

        acceptance = confirm_page.wait_for_acceptance(config.wait_for_ok_seconds)
        dialog_seen = acceptance.dialog_seen
        ok_clicked = acceptance.ok_clicked
        confirm_tab_closed = acceptance.confirm_tab_closed
        final_url = final_url or _safe_page_url(confirm_popup) or page.url

        if acceptance.accepted:
            LOGGER.info("要求受理を確認しました。window=%s", window.label)
        elif acceptance.accepted_candidate:
            LOGGER.info("確認タブ閉鎖のみを観測しました。暫定成功候補として扱います。window=%s", window.label)
        else:
            LOGGER.warning("要求受理シグナルが取れませんでした。window=%s", window.label)

        if confirm_popup is not None and not confirm_popup.is_closed():
            after_shot = store.save_screenshot(confirm_popup, f"{window.label}_after_convert")
            if after_shot is not None:
                screenshot_paths.append(after_shot)
            try:
                confirm_popup.close()
            except PlaywrightError:
                pass

        return RequestResult(
            window=window,
            accepted=acceptance.accepted,
            accepted_candidate=acceptance.accepted_candidate,
            final_url=final_url,
            parameter_page_detected=parameter_page_detected,
            confirm_page_detected=confirm_page_detected,
            parameter_bbox=parameter_bbox,
            confirm_bbox=confirm_bbox,
            dialog_seen=dialog_seen,
            ok_clicked=ok_clicked,
            confirm_tab_closed=confirm_tab_closed,
            screenshot_paths=tuple(screenshot_paths),
            message=None,
            started_at=started_at,
            finished_at=datetime.now(),
        )
    except Exception as exc:
        message = str(exc)
        LOGGER.exception("要求送信に失敗しました。window=%s", window.label)

        target_page = confirm_popup if confirm_popup is not None and not confirm_popup.is_closed() else page
        failure_shot = store.save_screenshot(target_page, f"{window.label}_failure")
        if failure_shot is not None:
            screenshot_paths.append(failure_shot)

        if final_url is None:
            final_url = _safe_page_url(target_page)

        return RequestResult(
            window=window,
            accepted=False,
            accepted_candidate=False,
            final_url=final_url,
            parameter_page_detected=parameter_page_detected,
            confirm_page_detected=confirm_page_detected,
            parameter_bbox=parameter_bbox,
            confirm_bbox=confirm_bbox,
            dialog_seen=dialog_seen,
            ok_clicked=ok_clicked,
            confirm_tab_closed=confirm_tab_closed,
            screenshot_paths=tuple(screenshot_paths),
            message=message,
            started_at=started_at,
            finished_at=datetime.now(),
        )


def _safe_page_url(page: Page | None) -> str | None:
    """閉じたページでも可能なら URL を返す。"""
    if page is None:
        return None
    try:
        return page.url
    except PlaywrightError:
        return None
