from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


DEFAULT_OUTPUT_DIR = Path("outputs") / "graph_mail_probe"
DEFAULT_SENDER = "noreply@i-ric.info"
DEFAULT_SUBJECT = "降雨データ変換完了のお知らせ"
DEFAULT_SCOPE = "https://graph.microsoft.com/Mail.Read https://graph.microsoft.com/User.Read offline_access"
DEFAULT_TOP = 100

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"

LOGGER = logging.getLogger(__name__)


def _configure_logging() -> None:
    """CLI 実行時のログ出力設定を行う。"""
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


def build_parser() -> argparse.ArgumentParser:
    """CLI 引数定義を構築する。"""
    parser = argparse.ArgumentParser(
        prog="graph-mail-probe",
        description="Microsoft Graph で会社メールにアクセスできるかを確認する実験スクリプト。",
    )
    parser.add_argument(
        "--tenant-id",
        default=os.getenv("GRAPH_TENANT_ID"),
        help="Azure AD テナント ID。未指定時は環境変数 GRAPH_TENANT_ID を使う。",
    )
    parser.add_argument(
        "--client-id",
        default=os.getenv("GRAPH_CLIENT_ID"),
        help="アプリ登録済みのクライアント ID。未指定時は環境変数 GRAPH_CLIENT_ID を使う。",
    )
    parser.add_argument(
        "--scope",
        default=DEFAULT_SCOPE,
        help="デバイスコード認証に使うスコープ。",
    )
    parser.add_argument(
        "--sender",
        default=DEFAULT_SENDER,
        help="絞り込み対象の送信者メールアドレス。",
    )
    parser.add_argument(
        "--subject",
        default=DEFAULT_SUBJECT,
        help="絞り込み対象の件名文字列。",
    )
    parser.add_argument(
        "--contains",
        action="append",
        default=[],
        help="本文プレビューに含まれてほしい追加条件。複数指定可。",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=DEFAULT_TOP,
        help="受信トレイから先頭何件を取得するか。",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="JSON 出力先ディレクトリ。",
    )
    return parser


def _ensure_dir(path: str | Path) -> Path:
    """保存先ディレクトリを作成して返す。"""
    result = Path(path)
    result.mkdir(parents=True, exist_ok=True)
    return result


def _timestamp() -> str:
    """ファイル名向けタイムスタンプを返す。"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _require_value(name: str, value: str | None) -> str:
    """必須引数の存在を確認する。"""
    if value:
        return value
    raise ValueError(
        f"{name} が未指定です。--{name.replace('_', '-')} または環境変数を設定してください。"
    )


def _post(url: str, *, data: dict[str, Any]) -> dict[str, Any]:
    """POST リクエストを送り、JSON を返す。"""
    response = requests.post(url, data=data, timeout=60)
    payload = response.json()
    if response.status_code >= 400:
        raise RuntimeError(f"POST 失敗: {url} status={response.status_code} payload={payload}")
    return payload


def _get(url: str, *, access_token: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
    """GET リクエストを送り、JSON を返す。"""
    merged_headers = {"Authorization": f"Bearer {access_token}"}
    if headers:
        merged_headers.update(headers)
    response = requests.get(url, headers=merged_headers, params=params, timeout=60)
    payload = response.json()
    if response.status_code >= 400:
        raise RuntimeError(f"GET 失敗: {url} status={response.status_code} payload={payload}")
    return payload


def acquire_access_token(*, tenant_id: str, client_id: str, scope: str) -> dict[str, Any]:
    """デバイスコードフローでアクセストークンを取得する。"""
    device_code_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/devicecode"
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

    device_code = _post(
        device_code_url,
        data={
            "client_id": client_id,
            "scope": scope,
        },
    )
    print(device_code["message"])

    interval = int(device_code.get("interval", 5))
    expires_at = time.monotonic() + int(device_code.get("expires_in", 900))
    while time.monotonic() < expires_at:
        time.sleep(interval)
        token_response = requests.post(
            token_url,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": client_id,
                "device_code": device_code["device_code"],
            },
            timeout=60,
        )
        payload = token_response.json()
        if token_response.status_code == 200:
            LOGGER.info("アクセストークンを取得しました。")
            return payload
        error = payload.get("error")
        if error in {"authorization_pending", "slow_down"}:
            if error == "slow_down":
                interval += 5
            continue
        raise RuntimeError(f"トークン取得に失敗しました: {payload}")

    raise RuntimeError("デバイスコード認証の待機がタイムアウトしました。")


def fetch_inbox_messages(*, access_token: str, top: int) -> dict[str, Any]:
    """受信トレイの先頭メッセージ群を取得する。"""
    return _get(
        f"{GRAPH_BASE_URL}/me/mailFolders/inbox/messages",
        access_token=access_token,
        params={
            "$top": top,
            "$orderby": "receivedDateTime desc",
            "$select": "id,subject,from,receivedDateTime,bodyPreview,webLink",
        },
    )


def filter_messages(
    messages: list[dict[str, Any]],
    *,
    sender: str,
    subject: str,
    contains: list[str],
) -> list[dict[str, Any]]:
    """送信者、件名、本文条件でメッセージを絞り込む。"""
    sender_lower = sender.lower()
    filtered: list[dict[str, Any]] = []
    for message in messages:
        from_address = (
            message.get("from", {})
            .get("emailAddress", {})
            .get("address", "")
        )
        body_preview = message.get("bodyPreview", "") or ""
        if sender_lower not in from_address.lower():
            continue
        if subject not in str(message.get("subject") or ""):
            continue
        if any(condition not in body_preview for condition in contains):
            continue
        filtered.append(message)
    return filtered


def extract_urls(messages: list[dict[str, Any]]) -> list[str]:
    """本文プレビューから URL を抽出する。"""
    urls: list[str] = []
    seen: set[str] = set()
    for message in messages:
        text = str(message.get("bodyPreview") or "")
        for token in text.split():
            if token.startswith("http://") or token.startswith("https://"):
                cleaned = token.rstrip(".,)")
                if cleaned not in seen:
                    seen.add(cleaned)
                    urls.append(cleaned)
    return urls


def save_outputs(
    output_dir: Path,
    *,
    profile: dict[str, Any],
    all_messages: list[dict[str, Any]],
    matched_messages: list[dict[str, Any]],
    extracted_urls: list[str],
) -> dict[str, Path]:
    """確認結果を JSON 保存する。"""
    stamp = _timestamp()
    inbox_path = output_dir / f"inbox_messages_{stamp}.json"
    matched_path = output_dir / f"matched_messages_{stamp}.json"
    urls_path = output_dir / f"matched_urls_{stamp}.json"
    summary_path = output_dir / f"graph_probe_summary_{stamp}.json"

    inbox_path.write_text(json.dumps(all_messages, ensure_ascii=False, indent=2), encoding="utf-8")
    matched_path.write_text(json.dumps(matched_messages, ensure_ascii=False, indent=2), encoding="utf-8")
    urls_path.write_text(json.dumps(extracted_urls, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path.write_text(
        json.dumps(
            {
                "profile": profile,
                "all_message_count": len(all_messages),
                "matched_message_count": len(matched_messages),
                "extracted_url_count": len(extracted_urls),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return {
        "inbox_path": inbox_path,
        "matched_path": matched_path,
        "urls_path": urls_path,
        "summary_path": summary_path,
    }


def main() -> int:
    """CLI エントリポイント。"""
    _configure_logging()
    parser = build_parser()
    args = parser.parse_args()

    tenant_id = _require_value("tenant_id", args.tenant_id)
    client_id = _require_value("client_id", args.client_id)
    output_dir = _ensure_dir(args.output_dir)

    token = acquire_access_token(
        tenant_id=tenant_id,
        client_id=client_id,
        scope=args.scope,
    )

    profile = _get(f"{GRAPH_BASE_URL}/me", access_token=token["access_token"])
    LOGGER.info("Graph API でプロフィールを取得しました。userPrincipalName=%s", profile.get("userPrincipalName"))

    inbox = fetch_inbox_messages(access_token=token["access_token"], top=args.top)
    messages = inbox.get("value", [])
    LOGGER.info("受信トレイから %s 件取得しました。", len(messages))

    matched_messages = filter_messages(
        messages,
        sender=args.sender,
        subject=args.subject,
        contains=args.contains,
    )
    LOGGER.info("条件一致メールは %s 件です。", len(matched_messages))

    extracted_urls = extract_urls(matched_messages)
    LOGGER.info("本文プレビューから URL を %s 件抽出しました。", len(extracted_urls))

    outputs = save_outputs(
        output_dir,
        profile=profile,
        all_messages=messages,
        matched_messages=matched_messages,
        extracted_urls=extracted_urls,
    )
    for path in outputs.values():
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
