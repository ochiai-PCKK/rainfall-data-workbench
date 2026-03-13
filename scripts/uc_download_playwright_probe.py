from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page
from playwright.sync_api import Playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PAGE_DIR = PROJECT_ROOT / "docs" / "uc_download_automation" / "sourse_page"
DEFAULT_PARAMETER_PAGE = SOURCE_PAGE_DIR / "Tool for Rain Data　メインページパラメータ入力.html"
DEFAULT_CONFIRM_PAGE = SOURCE_PAGE_DIR / "Tool for Rain Data　確認画面.html"
DEFAULT_LOGIN_URL = "https://tools.i-ric.info/login/"
DEFAULT_REAL_URL = "https://tools.i-ric.info/confirm/"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "uc_download_probe"
DEFAULT_PROFILE_DIR = PROJECT_ROOT / ".playwright" / "uc_download_profile"
DEFAULT_DOWNLOADS_DIR = DEFAULT_OUTPUT_DIR / "downloads"
DEFAULT_PERIOD_START = date(2010, 1, 2)
DEFAULT_PERIOD_END = date(2025, 12, 31)

PRESET_BBOXES: dict[str, tuple[float, float, float, float]] = {
    "yamatogawa": (34.33633333, 34.78113889, 135.43291667, 135.94752778),
    "higashiyoke": (34.48055556, 34.59694445, 135.55388889, 135.62527778),
    "nishiyoke": (34.40861112, 34.58944446, 135.49055556, 135.57194445),
    "yoke_combined": (34.40861112, 34.59694445, 135.49055556, 135.62527778),
}


def build_parser() -> argparse.ArgumentParser:
    """実験用 CLI の引数定義を構築する。"""
    parser = argparse.ArgumentParser(
        description="UC 降雨ダウンロード自動化の実現可能性を調べるための Playwright 実験 CLI。"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_local = subparsers.add_parser(
        "local-page",
        help="保存済み HTML を開き、selector と入力書き換えが通るかを確認する。",
    )
    p_local.add_argument(
        "--page-kind",
        choices=["parameter", "confirm"],
        default="parameter",
        help="--page-path を省略したときに開く保存ページの種類。",
    )
    p_local.add_argument(
        "--page-path",
        help="保存済み HTML の明示パス。省略時は docs 配下の既定ページを使う。",
    )
    p_local.add_argument(
        "--start-day",
        default="2025-01-01",
        help="パラメータ画面実験時に #start_day へ入れる値。",
    )
    p_local.add_argument(
        "--days",
        type=int,
        choices=[1, 2, 3],
        default=3,
        help="パラメータ画面実験時に select[name='days'] へ入れる値。",
    )
    p_local.add_argument(
        "--bbox",
        type=float,
        nargs=4,
        metavar=("SOUTH", "NORTH", "WEST", "EAST"),
        help="readonly の緯度経度 input へ直接入れる bbox 値。",
    )
    p_local.add_argument(
        "--bbox-preset",
        choices=sorted(PRESET_BBOXES),
        help="流域 bbox のプリセット名。--bbox 指定時は無視する。",
    )
    p_local.add_argument(
        "--bbox-pad-deg",
        type=float,
        default=0.0,
        help="bbox またはプリセットの各辺へ足す余白量（度）。",
    )
    p_local.add_argument(
        "--headless",
        action="store_true",
        help="ローカル実験を headless Chromium で実行する。",
    )
    p_local.add_argument(
        "--pause",
        action="store_true",
        help="Enter を押すまでブラウザを閉じない。",
    )
    p_local.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="スクリーンショットと JSON レポートの出力先ディレクトリ。",
    )

    p_login = subparsers.add_parser(
        "manual-login",
        help="ログインページを開き、必要ならメールアドレス入力とログイン押下まで行う。",
    )
    p_login.add_argument("--url", default=DEFAULT_LOGIN_URL, help="開くログインページの URL。")
    p_login.add_argument("--profile-dir", default=str(DEFAULT_PROFILE_DIR), help="永続プロファイルの保存先。")
    p_login.add_argument("--downloads-dir", default=str(DEFAULT_DOWNLOADS_DIR), help="ダウンロード保存先。")
    p_login.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="スクリーンショットと JSON レポートの出力先。")
    p_login.add_argument("--headless", action="store_true", help="headless Chromium で実行する。")
    p_login.add_argument(
        "--email",
        help="ログインページのメールアドレス欄へ自動入力する値。",
    )
    p_login.add_argument(
        "--submit-login",
        action="store_true",
        help="メール入力後にログインボタンを押す。",
    )
    p_login.add_argument(
        "--wait-after-submit-seconds",
        type=float,
        default=5.0,
        help="ログイン押下後の画面変化を待つ秒数。",
    )

    p_request = subparsers.add_parser(
        "request-link",
        help="保存済みログインセッションを使って、メールへダウンロードリンクを送る要求まで進める。",
    )
    p_request.add_argument("--url", default=DEFAULT_REAL_URL, help="開く実サイトの URL。")
    p_request.add_argument("--profile-dir", default=str(DEFAULT_PROFILE_DIR), help="永続プロファイルの保存先。")
    p_request.add_argument("--downloads-dir", default=str(DEFAULT_DOWNLOADS_DIR), help="ダウンロード保存先。")
    p_request.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="スクリーンショットと JSON レポートの出力先。")
    p_request.add_argument("--headless", action="store_true", help="headless Chromium で実行する。")
    p_request.add_argument("--start-day", required=True, help="要求に使う開始日。")
    p_request.add_argument("--days", type=int, choices=[1, 2, 3], required=True, help="要求に使う日数。")
    p_request.add_argument(
        "--bbox",
        type=float,
        nargs=4,
        metavar=("SOUTH", "NORTH", "WEST", "EAST"),
        help="地図ハンドルの代わりに readonly input へ直接入れる bbox 値。",
    )
    p_request.add_argument(
        "--bbox-preset",
        choices=sorted(PRESET_BBOXES),
        help="流域 bbox のプリセット名。--bbox 指定時は無視する。",
    )
    p_request.add_argument(
        "--bbox-pad-deg",
        type=float,
        default=0.0,
        help="bbox またはプリセットの各辺へ足す余白量（度）。",
    )
    p_request.add_argument(
        "--wait-for-ok-seconds",
        type=float,
        default=8.0,
        help="「変換開始」後に dialog や OK ボタンを監視する秒数。",
    )
    p_request.add_argument(
        "--pause",
        action="store_true",
        help="Enter を押すまでブラウザを閉じない。",
    )

    p_login_request = subparsers.add_parser(
        "login-and-request-link",
        help="ログインページから始め、OTP 完了後に同じブラウザでリンク送信要求まで進める。",
    )
    p_login_request.add_argument("--url", default=DEFAULT_LOGIN_URL, help="開くログインページの URL。")
    p_login_request.add_argument("--profile-dir", default=str(DEFAULT_PROFILE_DIR), help="永続プロファイルの保存先。")
    p_login_request.add_argument("--downloads-dir", default=str(DEFAULT_DOWNLOADS_DIR), help="ダウンロード保存先。")
    p_login_request.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="スクリーンショットと JSON レポートの出力先。")
    p_login_request.add_argument("--headless", action="store_true", help="headless Chromium で実行する。")
    p_login_request.add_argument("--email", required=True, help="ログインページのメールアドレス欄へ自動入力する値。")
    p_login_request.add_argument("--wait-after-submit-seconds", type=float, default=5.0, help="ログイン押下後の画面変化を待つ秒数。")
    p_login_request.add_argument("--wait-for-login-seconds", type=float, default=300.0, help="OTP 入力後にパラメータ画面が出るまで待つ秒数。")
    p_login_request.add_argument("--start-day", required=True, help="要求に使う開始日。")
    p_login_request.add_argument("--days", type=int, choices=[1, 2, 3], required=True, help="要求に使う日数。")
    p_login_request.add_argument(
        "--bbox",
        type=float,
        nargs=4,
        metavar=("SOUTH", "NORTH", "WEST", "EAST"),
        help="地図ハンドルの代わりに readonly input へ直接入れる bbox 値。",
    )
    p_login_request.add_argument(
        "--bbox-preset",
        choices=sorted(PRESET_BBOXES),
        help="流域 bbox のプリセット名。--bbox 指定時は無視する。",
    )
    p_login_request.add_argument(
        "--bbox-pad-deg",
        type=float,
        default=0.0,
        help="bbox またはプリセットの各辺へ足す余白量（度）。",
    )
    p_login_request.add_argument(
        "--wait-for-ok-seconds",
        type=float,
        default=8.0,
        help="「変換開始」後に dialog や OK ボタンを監視する秒数。",
    )
    p_login_request.add_argument(
        "--pause",
        action="store_true",
        help="Enter を押すまでブラウザを閉じない。",
    )

    p_live = subparsers.add_parser(
        "live-probe",
        help="ログイン後の実サイトでパラメータ入力から確認画面まで段階的に試す。",
    )
    p_live.add_argument("--url", default=DEFAULT_REAL_URL, help="開く実サイトの URL。")
    p_live.add_argument("--profile-dir", default=str(DEFAULT_PROFILE_DIR), help="永続プロファイルの保存先。")
    p_live.add_argument("--downloads-dir", default=str(DEFAULT_DOWNLOADS_DIR), help="ダウンロード保存先。")
    p_live.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="スクリーンショットと JSON レポートの出力先。")
    p_live.add_argument("--headless", action="store_true", help="headless Chromium で実行する。")
    p_live.add_argument(
        "--start-day",
        help="必要なら #start_day へ設定する日付。省略時は現在値を維持する。",
    )
    p_live.add_argument(
        "--days",
        type=int,
        choices=[1, 2, 3],
        help="必要なら select[name='days'] へ設定する日数。省略時は現在値を維持する。",
    )
    p_live.add_argument(
        "--bbox",
        type=float,
        nargs=4,
        metavar=("SOUTH", "NORTH", "WEST", "EAST"),
        help="地図ハンドルの代わりに readonly input へ直接入れる bbox 値。",
    )
    p_live.add_argument(
        "--bbox-preset",
        choices=sorted(PRESET_BBOXES),
        help="流域 bbox のプリセット名。--bbox 指定時は無視する。",
    )
    p_live.add_argument(
        "--bbox-pad-deg",
        type=float,
        default=0.0,
        help="bbox またはプリセットの各辺へ足す余白量（度）。",
    )
    p_live.add_argument(
        "--submit-confirm",
        action="store_true",
        help="「確認画面」を押して別タブの popup を捕まえる。",
    )
    p_live.add_argument(
        "--start-convert",
        action="store_true",
        help="確認画面で「変換開始」を押し、OK 系の通知を探す。",
    )
    p_live.add_argument(
        "--wait-for-ok-seconds",
        type=float,
        default=8.0,
        help="「変換開始」後に dialog や OK ボタンを監視する秒数。",
    )
    p_live.add_argument(
        "--pause",
        action="store_true",
        help="Enter を押すまでブラウザを閉じない。",
    )

    p_plan = subparsers.add_parser(
        "plan-periods",
        help="取得期間全体を 1/2/3 日単位の要求窓へ分割する。",
    )
    p_plan.add_argument(
        "--start-date",
        default=DEFAULT_PERIOD_START.isoformat(),
        help="開始日。YYYY-MM-DD。既定値は 2010-01-02。",
    )
    p_plan.add_argument(
        "--end-date",
        default=DEFAULT_PERIOD_END.isoformat(),
        help="終了日。YYYY-MM-DD。既定値は 2025-12-31。",
    )
    p_plan.add_argument(
        "--chunk-days",
        type=int,
        choices=[1, 2, 3],
        default=3,
        help="優先する要求日数。既定値は 3 日。",
    )
    p_plan.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="JSON 計画ファイルの出力先ディレクトリ。",
    )

    return parser


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _ensure_dir(path: str | Path) -> Path:
    result = Path(path)
    result.mkdir(parents=True, exist_ok=True)
    return result


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _expand_bbox(
    bbox: tuple[float, float, float, float] | list[float],
    pad_deg: float,
) -> tuple[float, float, float, float]:
    south, north, west, east = bbox
    expanded = (
        max(20.000001, south - pad_deg),
        min(47.999999, north + pad_deg),
        max(118.000001, west - pad_deg),
        min(149.999999, east + pad_deg),
    )
    return expanded


def _resolve_bbox(
    explicit_bbox: list[float] | tuple[float, float, float, float] | None,
    preset_name: str | None,
    pad_deg: float,
) -> tuple[float, float, float, float] | None:
    if explicit_bbox is not None:
        return _expand_bbox(tuple(explicit_bbox), pad_deg)
    if preset_name is None:
        return None
    return _expand_bbox(PRESET_BBOXES[preset_name], pad_deg)


def _build_period_windows(
    *,
    start_date: date,
    end_date: date,
    preferred_chunk_days: int,
) -> list[dict[str, Any]]:
    if end_date < start_date:
        raise ValueError("終了日は開始日より前にできません。")

    windows: list[dict[str, Any]] = []
    current = start_date
    while current <= end_date:
        remaining = (end_date - current).days + 1
        days = min(preferred_chunk_days, remaining)
        finish = current + timedelta(days=days - 1)
        windows.append(
            {
                "start_date": current.isoformat(),
                "end_date": finish.isoformat(),
                "days": days,
            }
        )
        current = finish + timedelta(days=1)
    return windows


def _ensure_page(context: BrowserContext) -> Page:
    return context.pages[0] if context.pages else context.new_page()


def _launch_context(
    playwright: Playwright,
    *,
    profile_dir: str | Path,
    downloads_dir: str | Path,
    headless: bool,
) -> BrowserContext:
    profile_path = _ensure_dir(profile_dir)
    downloads_path = _ensure_dir(downloads_dir)
    context = playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_path),
        headless=headless,
        accept_downloads=True,
        downloads_path=str(downloads_path),
        viewport={"width": 1600, "height": 1000},
    )
    context.set_default_timeout(10_000)
    return context


def _maybe_wait_for_enter(prompt: str) -> None:
    if not sys.stdin.isatty():
        print(prompt)
        return
    try:
        input(prompt)
    except EOFError:
        print(prompt)


def _fill_login_email(page: Page, email: str) -> None:
    _set_input_value(page, 'input[type="email"][name="email"]', email)


def _click_login_button(page: Page) -> None:
    page.locator('input[type="submit"][value="ログイン"]').click()


def _collect_login_page_state(page: Page) -> dict[str, Any]:
    return {
        "url": page.url,
        "has_email_input": _count(page, 'input[type="email"][name="email"]') > 0,
        "has_login_submit": _count(page, 'input[type="submit"][value="ログイン"]') > 0,
        "email_value": _value_or_none(page, 'input[type="email"][name="email"]'),
        "title": page.title(),
    }


def _write_json(output_dir: Path, stem: str, payload: dict[str, Any]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{stem}_{_timestamp()}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _save_screenshot(page: Page, output_dir: Path, stem: str) -> Path | None:
    if page.is_closed():
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{stem}_{_timestamp()}.png"
    page.screenshot(path=str(path), full_page=True)
    return path


def _value_or_none(page: Page, selector: str) -> str | None:
    locator = page.locator(selector)
    if locator.count() == 0:
        return None
    return locator.first.input_value()


def _count(page: Page, selector: str) -> int:
    return page.locator(selector).count()


def _set_input_value(page: Page, selector: str, value: str) -> None:
    page.locator(selector).evaluate(
        """(element, nextValue) => {
            element.value = nextValue;
            element.dispatchEvent(new Event("input", { bubbles: true }));
            element.dispatchEvent(new Event("change", { bubbles: true }));
        }""",
        value,
    )


def _set_bbox_inputs(page: Page, bbox: list[float] | tuple[float, float, float, float]) -> None:
    south, north, west, east = bbox
    page.evaluate(
        """([south, north, west, east]) => {
            const pairs = [
                ['input[name="south"]', south],
                ['input[name="nouth"]', north],
                ['input[name="west"]', west],
                ['input[name="east"]', east],
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
        [south, north, west, east],
    )


def _collect_parameter_page_state(page: Page) -> dict[str, Any]:
    return {
        "url": page.url,
        "has_start_day": _count(page, "#start_day") > 0,
        "has_days_select": _count(page, 'select[name="days"]') > 0,
        "has_confirm_submit": _count(page, 'input[type="submit"][value="確認画面"]') > 0,
        "start_day_value": _value_or_none(page, "#start_day"),
        "days_value": page.locator('select[name="days"]').input_value()
        if _count(page, 'select[name="days"]') > 0
        else None,
        "south_value": _value_or_none(page, 'input[name="south"]'),
        "north_value": _value_or_none(page, 'input[name="nouth"]'),
        "west_value": _value_or_none(page, 'input[name="west"]'),
        "east_value": _value_or_none(page, 'input[name="east"]'),
        "area_select_handles": _count(page, ".leaflet-areaselect-handle"),
    }


def _collect_confirm_page_state(page: Page) -> dict[str, Any]:
    return {
        "url": page.url,
        "has_start_convert": _count(page, 'input[type="submit"][value="変換開始"]') > 0,
        "has_cancel": _count(page, 'input[type="submit"][value="キャンセル"]') > 0,
        "start_day_value": _value_or_none(page, 'input[name="s_day"]'),
        "finish_day_value": _value_or_none(page, 'input[name="f_day"]'),
        "lat_s_value": _value_or_none(page, 'input[name="lat_s"]'),
        "lat_n_value": _value_or_none(page, 'input[name="lat_n"]'),
        "lng_w_value": _value_or_none(page, 'input[name="lng_w"]'),
        "lng_e_value": _value_or_none(page, 'input[name="lng_e"]'),
    }


def _apply_parameter_updates(
    page: Page,
    *,
    start_day: str | None,
    days: int | None,
    bbox: list[float] | tuple[float, float, float, float] | None,
) -> list[str]:
    notes: list[str] = []
    if start_day:
        _set_input_value(page, "#start_day", start_day)
        notes.append(f"#start_day に {start_day} を設定しました。")
    if days is not None:
        page.locator('select[name="days"]').select_option(str(days))
        notes.append(f"select[name='days'] に {days} を設定しました。")
    if bbox is not None:
        _set_bbox_inputs(page, bbox)
        south, north, west, east = bbox
        notes.append(
            "readonly の緯度経度 input へ bbox を設定しました "
            f"(south={south}, north={north}, west={west}, east={east})。"
        )
    return notes


def _wait_for_parameter_page(page: Page) -> None:
    if _count(page, "#start_day") > 0 and _count(page, 'select[name="days"]') > 0:
        return
    _maybe_wait_for_enter(
        "まだパラメータ画面が見つかりません。ブラウザ側でログインや画面遷移を済ませてから Enter を押してください。"
    )
    page.wait_for_load_state("domcontentloaded")
    if _count(page, "#start_day") == 0 or _count(page, 'select[name="days"]') == 0:
        raise RuntimeError("待機後もパラメータ画面の selector が見つかりませんでした。")


def _wait_for_parameter_page_after_login(page: Page, wait_seconds: float) -> None:
    """OTP 入力後に同一ブラウザでパラメータ画面が表示されるのを待つ。"""
    if _count(page, "#start_day") > 0 and _count(page, 'select[name="days"]') > 0:
        return

    print("OTP を入力してログインを完了してください。パラメータ画面が出るまで待機します。")
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if page.is_closed():
            raise RuntimeError("ログイン待機中にブラウザが閉じられました。")
        if _count(page, "#start_day") > 0 and _count(page, 'select[name="days"]') > 0:
            return
        page.wait_for_timeout(1000)

    raise RuntimeError("指定時間内にパラメータ画面へ遷移しませんでした。")


def _submit_to_confirm_popup(page: Page) -> Page:
    with page.expect_popup() as popup_info:
        page.locator('input[type="submit"][value="確認画面"]').click()
    popup = popup_info.value
    popup.wait_for_load_state("domcontentloaded")
    return popup


def _click_start_convert_and_probe_ok(page: Page, wait_seconds: float) -> dict[str, Any]:
    observed: dict[str, Any] = {
        "dialog_seen": False,
        "dialog_message": None,
        "ok_clicked": False,
        "page_closed_after_ok": False,
    }

    def _handle_dialog(dialog) -> None:
        observed["dialog_seen"] = True
        observed["dialog_message"] = dialog.message
        dialog.accept()

    page.on("dialog", _handle_dialog)
    page.locator('input[type="submit"][value="変換開始"]').click()

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if page.is_closed():
            observed["page_closed_after_ok"] = True
            return observed

        candidates = [
            page.get_by_role("button", name="OK"),
            page.get_by_role("link", name="OK"),
            page.locator('input[value="OK"]'),
            page.locator("text=OK"),
        ]
        for locator in candidates:
            try:
                if locator.count() > 0 and locator.first.is_visible():
                    locator.first.click()
                    observed["ok_clicked"] = True
                    page.wait_for_timeout(500)
                    observed["page_closed_after_ok"] = page.is_closed()
                    return observed
            except PlaywrightTimeoutError:
                continue
            except PlaywrightError:
                observed["page_closed_after_ok"] = True
                return observed
        try:
            page.wait_for_timeout(500)
        except PlaywrightError:
            observed["page_closed_after_ok"] = True
            return observed

    try:
        observed["page_closed_after_ok"] = page.is_closed()
    except PlaywrightError:
        observed["page_closed_after_ok"] = True
    return observed


def _request_link_from_parameter_page(
    page: Page,
    *,
    start_day: str,
    days: int,
    bbox: list[float] | tuple[float, float, float, float] | None,
    wait_for_ok_seconds: float,
    output_dir: Path,
    screenshot_prefix: str,
) -> tuple[list[str], dict[str, Any], list[str]]:
    """パラメータ画面から確認画面、変換開始までを一連で実行する。"""
    notes: list[str] = ["パラメータ画面からリンク送信要求の処理を開始しました。"]
    notes.extend(
        _apply_parameter_updates(
            page,
            start_day=start_day,
            days=days,
            bbox=bbox,
        )
    )

    observed: dict[str, Any] = {
        "parameter_page": _collect_parameter_page_state(page),
    }
    screenshot_paths: list[str] = []

    parameter_shot = _save_screenshot(page, output_dir, f"{screenshot_prefix}_parameter")
    if parameter_shot:
        screenshot_paths.append(str(parameter_shot))

    confirm_page = _submit_to_confirm_popup(page)
    notes.append("「確認画面」を押し、別タブの確認画面を取得しました。")
    observed["confirm_page"] = _collect_confirm_page_state(confirm_page)

    confirm_shot = _save_screenshot(confirm_page, output_dir, f"{screenshot_prefix}_confirm")
    if confirm_shot:
        screenshot_paths.append(str(confirm_shot))

    ok_probe = _click_start_convert_and_probe_ok(confirm_page, wait_for_ok_seconds)
    observed["start_convert_probe"] = ok_probe
    observed["email_link_request_attempted"] = True
    observed["email_link_request_acknowledged"] = bool(
        ok_probe["dialog_seen"] or ok_probe["ok_clicked"] or ok_probe["page_closed_after_ok"]
    )
    notes.append("「変換開始」を押し、メールリンク送信要求まで進めました。")
    if observed["email_link_request_acknowledged"]:
        notes.append("確認タブの閉鎖または OK 応答を検知しました。リンク送信要求は受理された可能性が高いです。")
    else:
        notes.append("リンク送信要求の明確な応答は取れていません。画面とメール到着を要確認です。")

    if not confirm_page.is_closed():
        after_shot = _save_screenshot(confirm_page, output_dir, f"{screenshot_prefix}_after_convert")
        if after_shot:
            screenshot_paths.append(str(after_shot))

    return notes, observed, screenshot_paths


def run_local_page(args: argparse.Namespace) -> int:
    """保存済み HTML を対象に selector と入力更新の基本動作を確認する。"""
    output_dir = _ensure_dir(args.output_dir)
    resolved_bbox = _resolve_bbox(args.bbox, args.bbox_preset, args.bbox_pad_deg)
    page_path = Path(args.page_path) if args.page_path else (
        DEFAULT_PARAMETER_PAGE if args.page_kind == "parameter" else DEFAULT_CONFIRM_PAGE
    )
    if not page_path.exists():
        raise FileNotFoundError(f"保存ページが見つかりません: {page_path}")

    with sync_playwright() as playwright:
        context = _launch_context(
            playwright,
            profile_dir=PROJECT_ROOT / ".playwright" / "local_probe_profile",
            downloads_dir=DEFAULT_DOWNLOADS_DIR,
            headless=args.headless,
        )
        try:
            page = _ensure_page(context)
            page.goto(page_path.resolve().as_uri())
            page.wait_for_load_state("domcontentloaded")

            notes: list[str] = [f"保存ページを開きました: {page_path.name}"]
            if args.page_kind == "parameter":
                notes.extend(
                    _apply_parameter_updates(
                        page,
                        start_day=args.start_day,
                        days=args.days,
                        bbox=resolved_bbox,
                    )
                )
                observed = _collect_parameter_page_state(page)
            else:
                observed = _collect_confirm_page_state(page)

            screenshot_path = _save_screenshot(page, output_dir, f"local_{args.page_kind}")
            report = {
                "command": "local-page",
                "success": True,
                "notes": notes,
                "observed": observed,
                "screenshot_path": str(screenshot_path) if screenshot_path else None,
                "page_path": str(page_path),
                "resolved_bbox": list(resolved_bbox) if resolved_bbox else None,
            }
            report_path = _write_json(output_dir, f"local_{args.page_kind}", report)
            print(report_path)

            if args.pause:
                _maybe_wait_for_enter("ブラウザを確認したら Enter を押してください。")
        finally:
            context.close()
    return 0


def run_manual_login(args: argparse.Namespace) -> int:
    """ログインページを開き、必要ならメール入力とログイン押下まで行う。"""
    output_dir = _ensure_dir(args.output_dir)
    with sync_playwright() as playwright:
        context = _launch_context(
            playwright,
            profile_dir=args.profile_dir,
            downloads_dir=args.downloads_dir,
            headless=args.headless,
        )
        try:
            page = _ensure_page(context)
            page.goto(args.url)
            page.wait_for_load_state("domcontentloaded")
            notes: list[str] = ["永続プロファイル付きでログインページを開きました。"]

            if args.email:
                _fill_login_email(page, args.email)
                notes.append(f"メールアドレス欄へ {args.email} を入力しました。")

            if args.submit_login:
                if not args.email:
                    raise ValueError("--submit-login を使うときは --email を指定してください。")
                _click_login_button(page)
                page.wait_for_timeout(int(args.wait_after_submit_seconds * 1000))
                notes.append("ログインボタンを押しました。")

            screenshot_path = _save_screenshot(page, output_dir, "manual_login_opened")
            print("ログイン用ブラウザを開きました。必要なら OTP 入力などを続けてください。")
            _maybe_wait_for_enter("作業が終わったら Enter を押してください。")

            page.wait_for_load_state("domcontentloaded")
            report = {
                "command": "manual-login",
                "success": True,
                "notes": notes
                + [
                    "このプロファイルは live-probe から再利用できます。",
                ],
                "observed": {
                    "final_url": page.url,
                    "login_page": _collect_login_page_state(page),
                    "parameter_page_detected": _count(page, "#start_day") > 0,
                },
                "screenshot_path": str(screenshot_path) if screenshot_path else None,
                "profile_dir": str(Path(args.profile_dir)),
            }
            report_path = _write_json(output_dir, "manual_login", report)
            print(report_path)
        finally:
            context.close()
    return 0


def run_request_link(args: argparse.Namespace) -> int:
    """保存済みログインセッションを再利用してリンク送信要求まで進める。"""
    output_dir = _ensure_dir(args.output_dir)
    resolved_bbox = _resolve_bbox(args.bbox, args.bbox_preset, args.bbox_pad_deg)
    with sync_playwright() as playwright:
        context = _launch_context(
            playwright,
            profile_dir=args.profile_dir,
            downloads_dir=args.downloads_dir,
            headless=args.headless,
        )
        try:
            page = _ensure_page(context)
            page.goto(args.url)
            page.wait_for_load_state("domcontentloaded")
            _wait_for_parameter_page(page)

            notes, observed, screenshot_paths = _request_link_from_parameter_page(
                page,
                start_day=args.start_day,
                days=args.days,
                bbox=resolved_bbox,
                wait_for_ok_seconds=args.wait_for_ok_seconds,
                output_dir=output_dir,
                screenshot_prefix="request_link",
            )

            report = {
                "command": "request-link",
                "success": True,
                "notes": [
                    "保存済みログインセッションを再利用しました。",
                    *notes,
                ],
                "observed": observed,
                "screenshot_paths": screenshot_paths,
                "profile_dir": str(Path(args.profile_dir)),
                "downloads_dir": str(Path(args.downloads_dir)),
                "resolved_bbox": list(resolved_bbox) if resolved_bbox else None,
            }
            report_path = _write_json(output_dir, "request_link", report)
            print(report_path)

            if args.pause:
                _maybe_wait_for_enter("ブラウザを確認したら Enter を押してください。")
        finally:
            context.close()
    return 0


def run_login_and_request_link(args: argparse.Namespace) -> int:
    """ログインから OTP 完了後のリンク送信要求までを同じブラウザで続けて実行する。"""
    output_dir = _ensure_dir(args.output_dir)
    resolved_bbox = _resolve_bbox(args.bbox, args.bbox_preset, args.bbox_pad_deg)
    with sync_playwright() as playwright:
        context = _launch_context(
            playwright,
            profile_dir=args.profile_dir,
            downloads_dir=args.downloads_dir,
            headless=args.headless,
        )
        try:
            page = _ensure_page(context)
            page.goto(args.url)
            page.wait_for_load_state("domcontentloaded")

            _fill_login_email(page, args.email)
            _click_login_button(page)
            page.wait_for_timeout(int(args.wait_after_submit_seconds * 1000))

            notes: list[str] = [
                "ログインページを開きました。",
                f"メールアドレス欄へ {args.email} を入力しました。",
                "ログインボタンを押しました。",
            ]

            _wait_for_parameter_page_after_login(page, args.wait_for_login_seconds)
            notes.append("OTP 完了後、同じブラウザでパラメータ画面へ到達しました。")

            flow_notes, observed, screenshot_paths = _request_link_from_parameter_page(
                page,
                start_day=args.start_day,
                days=args.days,
                bbox=resolved_bbox,
                wait_for_ok_seconds=args.wait_for_ok_seconds,
                output_dir=output_dir,
                screenshot_prefix="login_and_request",
            )
            notes.extend(flow_notes)

            report = {
                "command": "login-and-request-link",
                "success": True,
                "notes": notes,
                "observed": observed,
                "screenshot_paths": screenshot_paths,
                "profile_dir": str(Path(args.profile_dir)),
                "downloads_dir": str(Path(args.downloads_dir)),
                "resolved_bbox": list(resolved_bbox) if resolved_bbox else None,
            }
            report_path = _write_json(output_dir, "login_and_request", report)
            print(report_path)

            if args.pause:
                _maybe_wait_for_enter("ブラウザを確認したら Enter を押してください。")
        finally:
            context.close()
    return 0


def run_live_probe(args: argparse.Namespace) -> int:
    """ログイン後の実サイトで入力画面から確認画面までの操作可否を調べる。"""
    output_dir = _ensure_dir(args.output_dir)
    resolved_bbox = _resolve_bbox(args.bbox, args.bbox_preset, args.bbox_pad_deg)
    with sync_playwright() as playwright:
        context = _launch_context(
            playwright,
            profile_dir=args.profile_dir,
            downloads_dir=args.downloads_dir,
            headless=args.headless,
        )
        try:
            page = _ensure_page(context)
            page.goto(args.url)
            page.wait_for_load_state("domcontentloaded")
            _wait_for_parameter_page(page)

            notes: list[str] = [
                "永続プロファイル付きで実サイトを開きました。",
                "パラメータ画面の selector を検出しました。",
            ]
            notes.extend(
                _apply_parameter_updates(
                    page,
                    start_day=args.start_day,
                    days=args.days,
                    bbox=resolved_bbox,
                )
            )

            observed: dict[str, Any] = {
                "parameter_page": _collect_parameter_page_state(page),
            }
            screenshot_paths: list[str] = []
            parameter_shot = _save_screenshot(page, output_dir, "live_parameter")
            if parameter_shot:
                screenshot_paths.append(str(parameter_shot))

            confirm_page: Page | None = None
            if args.submit_confirm:
                confirm_page = _submit_to_confirm_popup(page)
                notes.append("「確認画面」を押し、別タブの確認画面を取得しました。")
                observed["confirm_page"] = _collect_confirm_page_state(confirm_page)
                confirm_shot = _save_screenshot(confirm_page, output_dir, "live_confirm")
                if confirm_shot:
                    screenshot_paths.append(str(confirm_shot))

            if args.start_convert:
                if confirm_page is None:
                    raise ValueError("--start-convert を使うときは --submit-confirm も必要です。")
                ok_probe = _click_start_convert_and_probe_ok(confirm_page, args.wait_for_ok_seconds)
                observed["start_convert_probe"] = ok_probe
                notes.append(
                    "「変換開始」を押し、dialog や OK 系の UI を監視しました。"
                )

            report = {
                "command": "live-probe",
                "success": True,
                "notes": notes,
                "observed": observed,
                "screenshot_paths": screenshot_paths,
                "profile_dir": str(Path(args.profile_dir)),
                "downloads_dir": str(Path(args.downloads_dir)),
                "resolved_bbox": list(resolved_bbox) if resolved_bbox else None,
            }
            report_path = _write_json(output_dir, "live_probe", report)
            print(report_path)

            if args.pause:
                _maybe_wait_for_enter("ブラウザを確認したら Enter を押してください。")
        finally:
            context.close()
    return 0


def run_plan_periods(args: argparse.Namespace) -> int:
    """全取得期間を 1/2/3 日単位の要求窓へ分割して出力する。"""
    output_dir = _ensure_dir(args.output_dir)
    start_date = _parse_date(args.start_date)
    end_date = _parse_date(args.end_date)
    windows = _build_period_windows(
        start_date=start_date,
        end_date=end_date,
        preferred_chunk_days=args.chunk_days,
    )
    report = {
        "command": "plan-periods",
        "success": True,
        "notes": [
            f"{start_date.isoformat()} から {end_date.isoformat()} までの要求窓を生成しました。",
            f"優先する要求日数は {args.chunk_days} 日です。",
        ],
        "observed": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "window_count": len(windows),
            "first_window": windows[0] if windows else None,
            "last_window": windows[-1] if windows else None,
        },
        "windows": windows,
    }
    report_path = _write_json(output_dir, "period_plan", report)
    print(report_path)
    return 0


def main() -> int:
    """CLI エントリポイント。"""
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "local-page":
        return run_local_page(args)
    if args.command == "manual-login":
        return run_manual_login(args)
    if args.command == "request-link":
        return run_request_link(args)
    if args.command == "login-and-request-link":
        return run_login_and_request_link(args)
    if args.command == "live-probe":
        return run_live_probe(args)
    if args.command == "plan-periods":
        return run_plan_periods(args)

    parser.error(f"不明なコマンドです: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
