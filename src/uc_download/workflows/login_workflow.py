from __future__ import annotations

import logging

from playwright.sync_api import Page

from ..models import RunConfig
from ..pages import LoginPage
from ..pages import ParameterPage


LOGGER = logging.getLogger(__name__)


def run_login_flow(page: Page, config: RunConfig) -> ParameterPage:
    """ログイン開始から OTP 完了後のパラメータ画面到達までを処理する。"""
    login_page = LoginPage(page)
    login_page.goto(config.login_url)
    LOGGER.info("ログインページを開きました。url=%s", config.login_url)

    if not login_page.is_visible():
        raise RuntimeError("ログインページの selector が見つかりません。")

    login_page.fill_email(config.email)
    LOGGER.info("メールアドレスを入力しました。email=%s", config.email)

    login_page.submit()
    LOGGER.info("ログインボタンを押しました。OTP 入力を待ちます。")

    parameter_page = ParameterPage(page)
    parameter_page.wait_until_ready(config.wait_for_login_seconds)
    LOGGER.info("パラメータ画面へ到達しました。url=%s", page.url)
    return parameter_page
