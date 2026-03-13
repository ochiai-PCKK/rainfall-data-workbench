from __future__ import annotations

import time

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from .. import selectors
from ..models import BBox


class ParameterPage:
    """パラメータ画面操作を担当する。"""

    def __init__(self, page: Page) -> None:
        self.page = page

    def is_ready(self) -> bool:
        """パラメータ画面の主要 selector が見えているかを返す。"""
        return (
            self.page.locator(selectors.PARAMETER_START_DAY).count() > 0
            and self.page.locator(selectors.PARAMETER_DAYS).count() > 0
        )

    def wait_until_ready(self, timeout_seconds: float) -> None:
        """パラメータ画面が使える状態になるまで待つ。"""
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self.page.is_closed():
                raise RuntimeError("パラメータ画面待機中にブラウザが閉じられました。")
            if self.is_ready():
                return
            self.page.wait_for_timeout(1000)
        raise RuntimeError("指定時間内にパラメータ画面へ到達しませんでした。")

    def set_start_day(self, value: str) -> None:
        """開始日を設定する。"""
        self._set_input_value(selectors.PARAMETER_START_DAY, value)

    def set_days(self, value: int) -> None:
        """取得日数を設定する。"""
        self.page.locator(selectors.PARAMETER_DAYS).select_option(str(value))

    def set_bbox(self, bbox: BBox) -> None:
        """bbox を readonly input へ直接設定する。"""
        self.page.evaluate(
            """([south, north, west, east, southSel, northSel, westSel, eastSel]) => {
                const pairs = [
                    [southSel, south],
                    [northSel, north],
                    [westSel, west],
                    [eastSel, east],
                ];
                for (const [selector, nextValue] of pairs) {
                    const element = document.querySelector(selector);
                    if (!element) {
                        throw new Error(`Missing selector: ${selector}`);
                    }
                    element.value = String(nextValue);
                    element.dispatchEvent(new Event("input", { bubbles: true }));
                    element.dispatchEvent(new Event("change", { bubbles: true }));
                }
            }""",
            [
                bbox.south,
                bbox.north,
                bbox.west,
                bbox.east,
                selectors.PARAMETER_SOUTH,
                selectors.PARAMETER_NORTH,
                selectors.PARAMETER_WEST,
                selectors.PARAMETER_EAST,
            ],
        )

    def open_confirm_popup(self) -> Page:
        """確認画面 popup を開いて返す。"""
        with self.page.expect_popup() as popup_info:
            self.page.locator(selectors.PARAMETER_CONFIRM_SUBMIT).click()
        popup = popup_info.value
        popup.wait_for_load_state("domcontentloaded")
        return popup

    def read_bbox(self) -> BBox | None:
        """現在画面に入っている bbox を返す。"""
        values = [
            self._value_or_none(selectors.PARAMETER_SOUTH),
            self._value_or_none(selectors.PARAMETER_NORTH),
            self._value_or_none(selectors.PARAMETER_WEST),
            self._value_or_none(selectors.PARAMETER_EAST),
        ]
        if any(value is None for value in values):
            return None
        south, north, west, east = values
        return BBox(float(south), float(north), float(west), float(east))

    def bring_to_front(self) -> None:
        """元画面を前面へ持ってくる。"""
        if not self.page.is_closed():
            self.page.bring_to_front()

    def snapshot(self) -> dict[str, object]:
        """現在画面の要約を返す。"""
        return {
            "url": self.page.url,
            "title": self.page.title(),
            "has_start_day": self.page.locator(selectors.PARAMETER_START_DAY).count() > 0,
            "has_days_select": self.page.locator(selectors.PARAMETER_DAYS).count() > 0,
            "has_confirm_submit": self.page.locator(selectors.PARAMETER_CONFIRM_SUBMIT).count() > 0,
            "start_day_value": self._value_or_none(selectors.PARAMETER_START_DAY),
            "days_value": self._value_or_none(selectors.PARAMETER_DAYS),
            "south_value": self._value_or_none(selectors.PARAMETER_SOUTH),
            "north_value": self._value_or_none(selectors.PARAMETER_NORTH),
            "west_value": self._value_or_none(selectors.PARAMETER_WEST),
            "east_value": self._value_or_none(selectors.PARAMETER_EAST),
        }

    def _set_input_value(self, selector: str, value: str) -> None:
        self.page.locator(selector).evaluate(
            """(element, nextValue) => {
                element.value = nextValue;
                element.dispatchEvent(new Event("input", { bubbles: true }));
                element.dispatchEvent(new Event("change", { bubbles: true }));
            }""",
            value,
        )

    def _value_or_none(self, selector: str) -> str | None:
        locator = self.page.locator(selector)
        if locator.count() == 0:
            return None
        try:
            return locator.first.input_value()
        except PlaywrightError:
            return None
