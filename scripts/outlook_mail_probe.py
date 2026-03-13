from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import Page
from playwright.sync_api import Playwright
from playwright.sync_api import sync_playwright


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PAGE_DIR = PROJECT_ROOT / "docs" / "uc_download_automation" / "sourse_page"
DEFAULT_SAVED_HTML = SOURCE_PAGE_DIR / "メール - 落合 優太 - Outlook.html"
DEFAULT_OUTLOOK_URL = "https://outlook.office.com/mail/"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "outlook_mail_probe"
DEFAULT_PROFILE_DIR = PROJECT_ROOT / ".playwright" / "outlook_mail_probe_profile"
DEFAULT_SENDER = "noreply@i-ric.info"
DEFAULT_SUBJECT = "降雨データ変換完了のお知らせ"
DEFAULT_URL_SUBSTRING = "ucrain.i-ric.info/download/"


LOGGER = logging.getLogger(__name__)


def _configure_logging() -> None:
    """CLI 実行時のログ出力設定を行う。"""
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


def build_parser() -> argparse.ArgumentParser:
    """実験用 CLI の引数定義を構築する。"""
    parser = argparse.ArgumentParser(
        prog="outlook-mail-probe",
        description="Outlook メールから対象メッセージを特定し、本文と URL を抽出する実験スクリプト。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_local = subparsers.add_parser(
        "local-html",
        help="保存済み Outlook HTML を開いて対象メール抽出を試す。",
    )
    p_local.add_argument(
        "--html-path",
        default=str(DEFAULT_SAVED_HTML),
        help="保存済み Outlook HTML のパス。",
    )
    p_local.add_argument(
        "--sender",
        default=DEFAULT_SENDER,
        help="対象メールの送信者文字列。",
    )
    p_local.add_argument(
        "--subject",
        default=DEFAULT_SUBJECT,
        help="対象メールの件名文字列。",
    )
    p_local.add_argument(
        "--contains",
        action="append",
        default=[],
        help="本文プレビューや行テキストに含まれてほしい追加条件。複数指定可。",
    )
    p_local.add_argument(
        "--match-index",
        type=int,
        default=0,
        help="一致したメールのうち何件目を対象にするか。0 が先頭。",
    )
    p_local.add_argument(
        "--url-substring",
        default=DEFAULT_URL_SUBSTRING,
        help="抽出 URL のうち特に注目する部分一致文字列。",
    )
    p_local.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="抽出結果の保存先ディレクトリ。",
    )
    p_local.add_argument(
        "--headless",
        action="store_true",
        help="headless Chromium で実行する。",
    )
    p_local.add_argument(
        "--pause",
        action="store_true",
        help="終了前に Enter を押すまでブラウザを閉じない。",
    )

    p_live = subparsers.add_parser(
        "live-outlook",
        help="実際の Outlook Web を開き、人手ログイン後に対象メール抽出を試す。",
    )
    p_live.add_argument(
        "--url",
        default=DEFAULT_OUTLOOK_URL,
        help="Outlook Web の URL。",
    )
    p_live.add_argument(
        "--profile-dir",
        default=str(DEFAULT_PROFILE_DIR),
        help="Playwright 用プロファイル保存先。",
    )
    p_live.add_argument(
        "--sender",
        default=DEFAULT_SENDER,
        help="対象メールの送信者文字列。",
    )
    p_live.add_argument(
        "--subject",
        default=DEFAULT_SUBJECT,
        help="対象メールの件名文字列。",
    )
    p_live.add_argument(
        "--contains",
        action="append",
        default=[],
        help="本文プレビューや行テキストに含まれてほしい追加条件。複数指定可。",
    )
    p_live.add_argument(
        "--match-index",
        type=int,
        default=0,
        help="一致したメールのうち何件目を対象にするか。0 が先頭。",
    )
    p_live.add_argument(
        "--url-substring",
        default=DEFAULT_URL_SUBSTRING,
        help="抽出 URL のうち特に注目する部分一致文字列。",
    )
    p_live.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="抽出結果の保存先ディレクトリ。",
    )
    p_live.add_argument(
        "--wait-for-login-seconds",
        type=float,
        default=300.0,
        help="人手ログインと受信トレイ表示を待つ秒数。",
    )
    p_live.add_argument(
        "--max-scroll-steps",
        type=int,
        default=30,
        help="メール一覧を追加探索する最大スクロール回数。",
    )
    p_live.add_argument(
        "--scroll-pause-ms",
        type=int,
        default=1200,
        help="スクロール後に一覧の読み込みを待つミリ秒。",
    )
    p_live.add_argument(
        "--headless",
        action="store_true",
        help="headless Chromium で実行する。",
    )
    p_live.add_argument(
        "--pause",
        action="store_true",
        help="終了前に Enter を押すまでブラウザを閉じない。",
    )

    return parser


def _timestamp() -> str:
    """ファイル名向けのタイムスタンプを返す。"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _ensure_dir(path: str | Path) -> Path:
    """保存先ディレクトリを作成して返す。"""
    result = Path(path)
    result.mkdir(parents=True, exist_ok=True)
    return result


def _maybe_pause(message: str) -> None:
    """対話端末でだけ Enter 待ちを行う。"""
    if not sys.stdin.isatty():
        return
    input(message)


def _open_local_page(playwright: Playwright, html_path: Path, *, headless: bool) -> Page:
    """保存済み HTML を Chromium で開いて返す。"""
    browser = playwright.chromium.launch(headless=headless)
    context = browser.new_context(viewport={"width": 1600, "height": 1000})
    context.set_default_timeout(30_000)
    page = context.new_page()
    page.goto(html_path.resolve().as_uri(), wait_until="domcontentloaded")
    page.wait_for_timeout(1_000)
    page._probe_browser = browser  # type: ignore[attr-defined]
    page._probe_context = context  # type: ignore[attr-defined]
    return page


def _open_live_outlook(playwright: Playwright, profile_dir: Path, url: str, *, headless: bool) -> Page:
    """Outlook Web を persistent context で開いて返す。"""
    context = playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        headless=headless,
        viewport={"width": 1600, "height": 1000},
    )
    context.set_default_timeout(30_000)
    context.set_default_navigation_timeout(60_000)
    page = context.pages[0] if context.pages else context.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    page._probe_context = context  # type: ignore[attr-defined]
    return page


def _close_probe_page(page: Page) -> None:
    """ページにぶら下げた browser/context を安全に閉じる。"""
    context = getattr(page, "_probe_context", None)
    browser = getattr(page, "_probe_browser", None)
    if context is not None:
        context.close()
    if browser is not None:
        browser.close()


def _wait_for_mail_list(page: Page, timeout_seconds: float) -> None:
    """メール一覧が見えるまで待つ。"""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if page.locator('[role="option"]').count() > 0:
            return
        page.wait_for_timeout(1_000)
    raise RuntimeError("指定時間内に Outlook のメール一覧が見つかりませんでした。")


def _collect_mail_rows(page: Page) -> list[dict[str, Any]]:
    """Outlook の一覧からメール候補を収集する。"""
    return page.evaluate(
        """() => {
            const rows = Array.from(document.querySelectorAll('[role="option"]'));
            return rows.map((row, domIndex) => {
                const senderTitle = row.querySelector('span[title*="@"]')?.getAttribute('title') ?? null;
                const subjectText = row.querySelector('.TtcXM')?.textContent?.trim() ?? null;
                const previewText = row.querySelector('.FqgPc')?.textContent?.trim() ?? null;
                const timestampTitle = row.querySelector('span[title*="202"]')?.getAttribute('title') ?? null;
                const timestampText = row.querySelector('span[title*="202"]')?.textContent?.trim() ?? null;
                return {
                    dom_index: domIndex,
                    sender: senderTitle,
                    subject: subjectText,
                    preview: previewText,
                    timestamp_title: timestampTitle,
                    timestamp_text: timestampText,
                    aria_label: row.getAttribute('aria-label') ?? '',
                    row_text: row.innerText ?? '',
                    data_index: row.getAttribute('data-index'),
                    selected: row.getAttribute('aria-selected') === 'true',
                };
            });
        }"""
    )


def _row_key(row: dict[str, Any]) -> str:
    """メール候補の重複排除に使うキーを返す。"""
    parts = [
        str(row.get("sender") or ""),
        str(row.get("subject") or ""),
        str(row.get("timestamp_title") or ""),
        str(row.get("preview") or ""),
    ]
    return " | ".join(parts)


def _filter_target_rows(
    rows: list[dict[str, Any]],
    *,
    sender: str,
    subject: str,
    contains: list[str],
) -> list[dict[str, Any]]:
    """送信者と件名で対象メール候補を絞り込む。"""
    filtered: list[dict[str, Any]] = []
    sender_lower = sender.lower()
    for row in rows:
        sender_candidates = " ".join(
            [
                str(row.get("sender") or ""),
                str(row.get("aria_label") or ""),
                str(row.get("row_text") or ""),
            ]
        ).lower()
        subject_candidates = " ".join(
            [
                str(row.get("subject") or ""),
                str(row.get("aria_label") or ""),
                str(row.get("row_text") or ""),
            ]
        )
        if sender_lower not in sender_candidates:
            continue
        if subject not in subject_candidates:
            continue
        combined_text = " ".join(
            [
                str(row.get("preview") or ""),
                str(row.get("aria_label") or ""),
                str(row.get("row_text") or ""),
            ]
        )
        if any(condition not in combined_text for condition in contains):
            continue
        filtered.append(row)
    return filtered


def _extract_selected_mail_detail(page: Page, dom_index: int) -> dict[str, Any]:
    """選択したメールから本文とリンク候補を抽出する。"""
    return page.evaluate(
        """(targetIndex) => {
            const rows = Array.from(document.querySelectorAll('[role="option"]'));
            const row = rows[targetIndex];
            if (!row) {
                throw new Error(`メール行が見つかりません: ${targetIndex}`);
            }

            const readingPane =
                document.querySelector('#ReadingPaneContainerId') ||
                document.querySelector('[aria-label="閲覧ウィンドウ"]');

            const rowLinks = Array.from(row.querySelectorAll('a[href]')).map((link) => link.href);
            const paneLinks = readingPane
                ? Array.from(readingPane.querySelectorAll('a[href]')).map((link) => link.href)
                : [];

            return {
                row_text: row.innerText ?? '',
                row_aria_label: row.getAttribute('aria-label') ?? '',
                reading_pane_text: readingPane ? (readingPane.innerText ?? '') : '',
                reading_pane_html_snippet: readingPane ? readingPane.innerHTML.slice(0, 20000) : '',
                row_links: rowLinks,
                reading_pane_links: paneLinks,
            };
        }""",
        dom_index,
    )


def _extract_urls(raw_texts: list[str], hrefs: list[str], *, url_substring: str) -> dict[str, list[str]]:
    """本文や href から URL を抽出し、注目 URL を分離する。"""
    pattern = re.compile(r"https?://[^\s<>'\"）)]+")
    ordered: list[str] = []
    seen: set[str] = set()

    def _append(candidate: str) -> None:
        cleaned = candidate.strip().rstrip(".,)")
        if not cleaned or cleaned in seen:
            return
        seen.add(cleaned)
        ordered.append(cleaned)

    for text in raw_texts:
        for match in pattern.findall(text):
            _append(match)
    for href in hrefs:
        _append(href)

    target_urls = [url for url in ordered if url_substring in url]
    return {
        "all_urls": ordered,
        "target_urls": target_urls,
    }


def _save_outputs(
    output_dir: Path,
    *,
    rows: list[dict[str, Any]],
    matches: list[dict[str, Any]],
    selected: dict[str, Any],
    mail_detail: dict[str, Any],
    urls: dict[str, list[str]],
) -> dict[str, Path]:
    """抽出結果を JSON / TXT で保存する。"""
    stamp = _timestamp()
    candidates_path = output_dir / f"mail_candidates_{stamp}.json"
    selected_path = output_dir / f"selected_mail_{stamp}.json"
    body_path = output_dir / f"selected_mail_body_{stamp}.txt"
    urls_path = output_dir / f"selected_mail_urls_{stamp}.json"

    candidates_payload = {
        "all_rows_count": len(rows),
        "matched_rows_count": len(matches),
        "rows": rows,
        "matched_rows": matches,
    }
    selected_payload = {
        "selected_row": selected,
        "mail_detail": mail_detail,
        "urls": urls,
    }

    candidates_path.write_text(json.dumps(candidates_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    selected_path.write_text(json.dumps(selected_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    body_text = "\n\n".join(
        [
            "=== row_text ===",
            str(mail_detail.get("row_text") or ""),
            "",
            "=== row_aria_label ===",
            str(mail_detail.get("row_aria_label") or ""),
            "",
            "=== reading_pane_text ===",
            str(mail_detail.get("reading_pane_text") or ""),
        ]
    )
    body_path.write_text(body_text, encoding="utf-8")
    urls_path.write_text(json.dumps(urls, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "candidates_path": candidates_path,
        "selected_path": selected_path,
        "body_path": body_path,
        "urls_path": urls_path,
    }


def _probe_page(
    page: Page,
    *,
    sender: str,
    subject: str,
    contains: list[str],
    match_index: int,
    url_substring: str,
    output_dir: Path,
) -> dict[str, Path]:
    """ページ上の対象メールを抽出して保存する。"""
    rows = _collect_mail_rows(page)
    if not rows:
        raise RuntimeError("Outlook のメール候補行が見つかりませんでした。")

    matches = _filter_target_rows(rows, sender=sender, subject=subject, contains=contains)
    if not matches:
        raise RuntimeError(
            f"対象メールが見つかりませんでした。sender={sender} subject={subject} contains={contains}"
        )
    if match_index < 0 or match_index >= len(matches):
        raise ValueError(
            f"match_index が範囲外です。match_index={match_index} matched_rows={len(matches)}"
        )

    selected = matches[match_index]
    LOGGER.info(
        "対象メールを選択します。sender=%s subject=%s dom_index=%s",
        sender,
        subject,
        selected["dom_index"],
    )
    target_locator = page.locator('[role="option"]').nth(selected["dom_index"])
    try:
        target_locator.click(timeout=5_000)
    except Exception:
        target_locator.evaluate("(element) => element.click()")
    page.wait_for_timeout(1_500)

    mail_detail = _extract_selected_mail_detail(page, int(selected["dom_index"]))
    urls = _extract_urls(
        [
            str(selected.get("row_text") or ""),
            str(selected.get("aria_label") or ""),
            str(mail_detail.get("row_text") or ""),
            str(mail_detail.get("row_aria_label") or ""),
            str(mail_detail.get("reading_pane_text") or ""),
        ],
        list(mail_detail.get("row_links") or []) + list(mail_detail.get("reading_pane_links") or []),
        url_substring=url_substring,
    )
    if not urls["target_urls"]:
        LOGGER.warning("注目 URL を抽出できませんでした。url_substring=%s", url_substring)
    else:
        LOGGER.info("注目 URL を %s 件抽出しました。", len(urls["target_urls"]))

    return _save_outputs(
        output_dir,
        rows=rows,
        matches=matches,
        selected=selected,
        mail_detail=mail_detail,
        urls=urls,
    )


def _scroll_mail_list(page: Page, pause_ms: int) -> None:
    """Outlook のメール一覧領域を 1 回分スクロールする。"""
    page.evaluate(
        """() => {
            const row = document.querySelector('[role="option"]');
            if (!row) {
                window.scrollBy(0, 1200);
                return;
            }
            let current = row.parentElement;
            let scrollTarget = null;
            while (current) {
                if (current.scrollHeight > current.clientHeight + 20) {
                    scrollTarget = current;
                    break;
                }
                current = current.parentElement;
            }
            if (scrollTarget) {
                scrollTarget.scrollTop += Math.max(scrollTarget.clientHeight * 0.8, 600);
            } else {
                window.scrollBy(0, 1200);
            }
        }"""
    )
    page.wait_for_timeout(pause_ms)


def _probe_live_page(
    page: Page,
    *,
    sender: str,
    subject: str,
    contains: list[str],
    match_index: int,
    url_substring: str,
    output_dir: Path,
    max_scroll_steps: int,
    scroll_pause_ms: int,
) -> dict[str, Path]:
    """Outlook Web の一覧をスクロールしながら対象メールを探して保存する。"""
    seen_rows: dict[str, dict[str, Any]] = {}
    visible_matches: list[dict[str, Any]] = []
    stagnant_steps = 0

    for step in range(max_scroll_steps + 1):
        current_rows = _collect_mail_rows(page)
        for row in current_rows:
            seen_rows.setdefault(_row_key(row), row)

        visible_matches = _filter_target_rows(current_rows, sender=sender, subject=subject, contains=contains)
        if len(visible_matches) > match_index:
            LOGGER.info(
                "対象メールを一覧上で見つけました。step=%s visible_matches=%s",
                step,
                len(visible_matches),
            )
            return _probe_page(
                page,
                sender=sender,
                subject=subject,
                contains=contains,
                match_index=match_index,
                url_substring=url_substring,
                output_dir=output_dir,
            )

        before_count = len(seen_rows)
        if step < max_scroll_steps:
            LOGGER.info(
                "対象メールを探索中です。step=%s seen_rows=%s visible_matches=%s",
                step,
                before_count,
                len(visible_matches),
            )
            _scroll_mail_list(page, scroll_pause_ms)
            after_rows = _collect_mail_rows(page)
            for row in after_rows:
                seen_rows.setdefault(_row_key(row), row)
            after_count = len(seen_rows)
            if after_count == before_count:
                stagnant_steps += 1
            else:
                stagnant_steps = 0
            if stagnant_steps >= 3:
                break

    all_rows = list(seen_rows.values())
    matches = _filter_target_rows(all_rows, sender=sender, subject=subject, contains=contains)
    candidates_path = _save_outputs(
        output_dir,
        rows=all_rows,
        matches=matches,
        selected={},
        mail_detail={},
        urls={"all_urls": [], "target_urls": []},
    )["candidates_path"]
    raise RuntimeError(
        "Outlook 一覧をスクロールしても対象メールを見つけられませんでした。"
        f" seen_rows={len(all_rows)} matched_rows={len(matches)} candidates={candidates_path}"
    )


def run_local_html(args: argparse.Namespace) -> int:
    """保存済み Outlook HTML を対象に抽出実験を行う。"""
    html_path = Path(args.html_path)
    if not html_path.exists():
        raise FileNotFoundError(f"保存済み HTML が見つかりません: {html_path}")

    output_dir = _ensure_dir(args.output_dir)
    with sync_playwright() as playwright:
        page = _open_local_page(playwright, html_path, headless=args.headless)
        try:
            outputs = _probe_page(
                page,
                sender=args.sender,
                subject=args.subject,
                contains=args.contains,
                match_index=args.match_index,
                url_substring=args.url_substring,
                output_dir=output_dir,
            )
            for path in outputs.values():
                print(path)
            if args.pause:
                _maybe_pause("ブラウザを確認したら Enter を押してください。")
        finally:
            _close_probe_page(page)
    return 0


def run_live_outlook(args: argparse.Namespace) -> int:
    """Outlook Web を対象に抽出実験を行う。"""
    output_dir = _ensure_dir(args.output_dir)
    profile_dir = _ensure_dir(args.profile_dir)

    with sync_playwright() as playwright:
        page = _open_live_outlook(playwright, profile_dir, args.url, headless=args.headless)
        try:
            LOGGER.info("Outlook Web を開きました。必要なら人手でログインしてください。")
            if page.locator('[role="option"]').count() == 0:
                _maybe_pause("受信トレイが表示されたら Enter を押してください。")
            _wait_for_mail_list(page, args.wait_for_login_seconds)

            outputs = _probe_live_page(
                page,
                sender=args.sender,
                subject=args.subject,
                contains=args.contains,
                match_index=args.match_index,
                url_substring=args.url_substring,
                output_dir=output_dir,
                max_scroll_steps=args.max_scroll_steps,
                scroll_pause_ms=args.scroll_pause_ms,
            )
            for path in outputs.values():
                print(path)
            if args.pause:
                _maybe_pause("ブラウザを確認したら Enter を押してください。")
        finally:
            _close_probe_page(page)
    return 0


def main() -> int:
    """CLI エントリポイント。"""
    _configure_logging()
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "local-html":
        return run_local_html(args)
    if args.command == "live-outlook":
        return run_live_outlook(args)

    parser.error(f"不明なコマンドです: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
