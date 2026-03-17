from __future__ import annotations

import time

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .. import selectors
from ..models import AcceptanceResult
from ..models import BBox


class ConfirmPage:
    """確認画面操作と受理判定を担当する。"""

    def __init__(self, page: Page) -> None:
        self.page = page

    def is_ready(self) -> bool:
        """確認画面の主要 selector が見えているかを返す。"""
        return self.page.locator(selectors.CONFIRM_START_CONVERT).count() > 0

    def wait_until_ready(self, timeout_seconds: float = 10.0) -> None:
        """確認画面が使える状態になるまで待つ。"""
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self.page.is_closed():
                raise RuntimeError("確認画面待機中にタブが閉じられました。")
            if self.is_ready():
                return
            self.page.wait_for_timeout(250)
        raise RuntimeError("指定時間内に確認画面が開きませんでした。")

    def start_convert(self) -> None:
        """変換開始ボタンを押す。"""
        self.page.locator(selectors.CONFIRM_START_CONVERT).click()

    def wait_for_acceptance(self, timeout_seconds: float) -> AcceptanceResult:
        """OK、dialog、確認タブ閉鎖を監視して結果を返す。"""
        observed = {
            "dialog_seen": False,
            "dialog_message": None,
            "ok_clicked": False,
            "confirm_tab_closed": False,
            "server_error_tab_seen": False,
            "server_error_tab_closed": False,
            "server_error_tab_url": None,
            "server_error_tab_title": None,
            "server_error_on_confirm_page": False,
        }

        def _handle_dialog(dialog) -> None:
            observed["dialog_seen"] = True
            observed["dialog_message"] = dialog.message
            dialog.accept()

        self.page.on("dialog", _handle_dialog)
        self.start_convert()

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self._is_server_error_page(self.page):
                observed["server_error_tab_seen"] = True
                observed["server_error_tab_url"] = self._safe_url(self.page)
                observed["server_error_tab_title"] = self._safe_title(self.page)
                observed["server_error_on_confirm_page"] = True
                try:
                    self.page.close()
                    observed["server_error_tab_closed"] = True
                    observed["confirm_tab_closed"] = True
                except PlaywrightError:
                    observed["server_error_tab_closed"] = False
                return AcceptanceResult(**observed)

            self._close_server_error_tabs(observed)

            if self.page.is_closed():
                observed["confirm_tab_closed"] = True
                break

            for locator in self._ok_locators():
                try:
                    if locator.count() > 0 and locator.first.is_visible():
                        locator.first.click()
                        observed["ok_clicked"] = True
                        self.page.wait_for_timeout(500)
                        observed["confirm_tab_closed"] = self.page.is_closed()
                        return AcceptanceResult(**observed)
                except PlaywrightTimeoutError:
                    continue
                except PlaywrightError:
                    observed["confirm_tab_closed"] = True
                    return AcceptanceResult(**observed)

            try:
                self.page.wait_for_timeout(500)
            except PlaywrightError:
                observed["confirm_tab_closed"] = True
                break

        if not observed["confirm_tab_closed"]:
            try:
                observed["confirm_tab_closed"] = self.page.is_closed()
            except PlaywrightError:
                observed["confirm_tab_closed"] = True
        return AcceptanceResult(**observed)

    def _close_server_error_tabs(self, observed: dict[str, object]) -> None:
        """500 エラーの新規タブを検知したら閉じる。"""
        context = self.page.context
        for tab in context.pages:
            if tab == self.page or tab.is_closed():
                continue
            if self._is_server_error_page(tab):
                observed["server_error_tab_seen"] = True
                observed["server_error_tab_url"] = self._safe_url(tab)
                observed["server_error_tab_title"] = self._safe_title(tab)
                try:
                    tab.close()
                    observed["server_error_tab_closed"] = True
                except PlaywrightError:
                    observed["server_error_tab_closed"] = False

    def _is_server_error_page(self, page: Page) -> bool:
        """500 Internal Server Error 相当のタブかを判定する。"""
        title = (self._safe_title(page) or "").lower()
        if "500 internal server error" in title:
            return True
        url = (self._safe_url(page) or "").lower()
        if "/convert/" in url:
            try:
                body = page.locator("body")
                if body.count() > 0:
                    text = body.first.inner_text(timeout=500).lower()
                    if "internal server error" in text:
                        return True
            except PlaywrightError:
                return False
        return False

    def _safe_title(self, page: Page) -> str | None:
        try:
            return page.title()
        except PlaywrightError:
            return None

    def _safe_url(self, page: Page) -> str | None:
        try:
            return page.url
        except PlaywrightError:
            return None

    def snapshot(self) -> dict[str, object]:
        """現在画面の要約を返す。"""
        return {
            "url": self.page.url,
            "title": self.page.title(),
            "has_start_convert": self.page.locator(selectors.CONFIRM_START_CONVERT).count() > 0,
            "has_cancel": self.page.locator(selectors.CONFIRM_CANCEL).count() > 0,
            "lat_s_value": self._value_or_none(selectors.CONFIRM_LAT_S),
            "lat_n_value": self._value_or_none(selectors.CONFIRM_LAT_N),
            "lng_w_value": self._value_or_none(selectors.CONFIRM_LNG_W),
            "lng_e_value": self._value_or_none(selectors.CONFIRM_LNG_E),
        }

    def read_bbox(self) -> BBox | None:
        """確認画面に表示された bbox を返す。"""
        values = [
            self._value_or_none(selectors.CONFIRM_LAT_S),
            self._value_or_none(selectors.CONFIRM_LAT_N),
            self._value_or_none(selectors.CONFIRM_LNG_W),
            self._value_or_none(selectors.CONFIRM_LNG_E),
        ]
        if any(value is None for value in values):
            return None
        south, north, west, east = values
        return BBox(float(south), float(north), float(west), float(east))

    def _ok_locators(self):
        return [
            self.page.get_by_role("button", name="OK"),
            self.page.get_by_role("link", name="OK"),
            self.page.locator(selectors.OK_INPUT),
            self.page.locator(selectors.OK_TEXT),
        ]

    def _value_or_none(self, selector: str) -> str | None:
        locator = self.page.locator(selector)
        if locator.count() == 0:
            return None
        try:
            return locator.first.input_value()
        except PlaywrightError:
            return None
