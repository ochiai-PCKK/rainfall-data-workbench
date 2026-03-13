from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

from playwright.sync_api import Browser
from playwright.sync_api import BrowserContext
from playwright.sync_api import Page
from playwright.sync_api import Playwright
from playwright.sync_api import sync_playwright

from .models import RunConfig


@dataclass
class BrowserSession:
    """起動済みブラウザ一式をまとめたコンテナ。"""

    playwright: Playwright
    browser: Browser
    context: BrowserContext
    page: Page


@contextmanager
def open_browser_session(config: RunConfig):
    """Playwright ブラウザを起動してセッションを返す。"""
    with sync_playwright() as playwright:
        config.downloads_dir.mkdir(parents=True, exist_ok=True)
        browser = playwright.chromium.launch(headless=config.headless)
        context = browser.new_context(
            viewport={"width": 1600, "height": 1000},
            accept_downloads=True,
        )
        context.set_default_timeout(30_000)
        context.set_default_navigation_timeout(60_000)
        page = context.new_page()
        session = BrowserSession(
            playwright=playwright,
            browser=browser,
            context=context,
            page=page,
        )
        try:
            yield session
        finally:
            context.close()
            browser.close()
