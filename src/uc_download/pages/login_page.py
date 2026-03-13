from __future__ import annotations

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import Page

from .. import selectors


class LoginPage:
    """ログインページ操作を担当する。"""

    def __init__(self, page: Page) -> None:
        self.page = page

    def goto(self, url: str) -> None:
        """ログインページを開く。"""
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                self.page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                return
            except PlaywrightTimeoutError as exc:
                last_error = exc
                if attempt >= 3:
                    break
                self.page.wait_for_timeout(2_000)
        raise RuntimeError(f"ログインページの表示がタイムアウトしました: {url}") from last_error

    def fill_email(self, email: str) -> None:
        """メールアドレス欄へ値を入力する。"""
        self.page.locator(selectors.LOGIN_EMAIL).fill(email)

    def submit(self) -> None:
        """ログインボタンを押す。"""
        self.page.locator(selectors.LOGIN_SUBMIT).click()

    def is_visible(self) -> bool:
        """ログインページの主要 selector が見えているかを返す。"""
        return (
            self.page.locator(selectors.LOGIN_EMAIL).count() > 0
            and self.page.locator(selectors.LOGIN_SUBMIT).count() > 0
        )

    def snapshot(self) -> dict[str, str | bool | None]:
        """現在画面の要約を返す。"""
        email_locator = self.page.locator(selectors.LOGIN_EMAIL)
        return {
            "url": self.page.url,
            "title": self.page.title(),
            "has_email_input": email_locator.count() > 0,
            "has_login_submit": self.page.locator(selectors.LOGIN_SUBMIT).count() > 0,
            "email_value": email_locator.first.input_value() if email_locator.count() > 0 else None,
        }
