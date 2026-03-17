from __future__ import annotations

from datetime import datetime
from pathlib import Path

import requests

from .models import MailEntry
from .models import ZipDownloadResult


EXPIRED_HTTP_STATUSES = {404, 410}
EXPIRED_RESPONSE_HINTS = (
    "expired",
    "期限",
    "失効",
    "無効",
    "not found",
    "download url",
)
MAX_RESPONSE_PREVIEW_CHARS = 1024


def download_zip_from_mail_entry(
    entry: MailEntry,
    *,
    downloads_dir: Path,
    timeout_seconds: float = 120.0,
) -> ZipDownloadResult:
    """メール本文から得た URL へアクセスし、ZIP を保存する。"""
    downloads_dir.mkdir(parents=True, exist_ok=True)
    zip_path = downloads_dir / f"{entry.source_id}.zip"
    if zip_path.exists() and zip_path.stat().st_size > 0:
        return ZipDownloadResult(
            source_id=entry.source_id,
            download_url=entry.download_url,
            period_start=entry.period_start,
            period_end=entry.period_end,
            zip_path=zip_path,
            status="already_exists",
            http_status=None,
            downloaded_at=datetime.now(),
            message="既存 ZIP を再利用しました。",
            response_preview=None,
        )

    temp_path = zip_path.with_suffix(".zip.part")
    try:
        with requests.get(entry.download_url, stream=True, timeout=timeout_seconds) as response:
            if response.status_code != 200:
                status = "expired" if response.status_code in EXPIRED_HTTP_STATUSES else "failed"
                response_preview = _extract_response_preview(response)
                return ZipDownloadResult(
                    source_id=entry.source_id,
                    download_url=entry.download_url,
                    period_start=entry.period_start,
                    period_end=entry.period_end,
                    zip_path=None,
                    status=status,
                    http_status=response.status_code,
                    downloaded_at=datetime.now(),
                    message=_build_http_error_message(response.status_code, status),
                    response_preview=response_preview,
                )

            content_type = (response.headers.get("Content-Type") or "").lower()
            with temp_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 64):
                    if chunk:
                        handle.write(chunk)

        if not temp_path.exists() or temp_path.stat().st_size == 0:
            return ZipDownloadResult(
                source_id=entry.source_id,
                download_url=entry.download_url,
                period_start=entry.period_start,
                period_end=entry.period_end,
                zip_path=None,
                status="failed",
                http_status=200,
                downloaded_at=datetime.now(),
                message="ZIP 保存後のファイルサイズが 0 でした。",
                response_preview=None,
            )

        first_bytes = temp_path.read_bytes()[:4]
        if first_bytes[:2] != b"PK" and "zip" not in content_type:
            non_zip_status = _classify_non_zip_response(temp_path)
            response_preview = _extract_file_preview(temp_path)
            temp_path.unlink(missing_ok=True)
            return ZipDownloadResult(
                source_id=entry.source_id,
                download_url=entry.download_url,
                period_start=entry.period_start,
                period_end=entry.period_end,
                zip_path=None,
                status=non_zip_status,
                http_status=200,
                downloaded_at=datetime.now(),
                message=_build_non_zip_message(content_type=content_type, status=non_zip_status),
                response_preview=response_preview,
            )

        temp_path.replace(zip_path)
        return ZipDownloadResult(
            source_id=entry.source_id,
            download_url=entry.download_url,
            period_start=entry.period_start,
            period_end=entry.period_end,
            zip_path=zip_path,
            status="downloaded",
            http_status=200,
            downloaded_at=datetime.now(),
            message=None,
            response_preview=None,
        )
    except requests.RequestException as exc:
        temp_path.unlink(missing_ok=True)
        return ZipDownloadResult(
            source_id=entry.source_id,
            download_url=entry.download_url,
            period_start=entry.period_start,
            period_end=entry.period_end,
            zip_path=None,
            status="failed",
            http_status=None,
            downloaded_at=datetime.now(),
            message=str(exc),
            response_preview=None,
        )


def _build_http_error_message(status_code: int, status: str) -> str:
    if status == "expired":
        return f"HTTP {status_code} が返りました。URL の期限切れまたは無効の可能性があります。"
    return f"HTTP {status_code} が返りました。"


def _classify_non_zip_response(path: Path) -> str:
    preview = path.read_text(encoding="utf-8", errors="ignore")[:1024].lower()
    if any(hint in preview for hint in EXPIRED_RESPONSE_HINTS):
        return "expired"
    return "failed"


def _build_non_zip_message(*, content_type: str, status: str) -> str:
    if status == "expired":
        return (
            "ZIP ではない応答が返りました。"
            f"URL の期限切れまたは無効の可能性があります。content_type={content_type}"
        )
    return f"ZIP ではない応答の可能性があります。content_type={content_type}"


def _extract_response_preview(response: requests.Response) -> str | None:
    try:
        preview = response.text[:MAX_RESPONSE_PREVIEW_CHARS]
    except Exception:
        return None
    return preview.strip() or None


def _extract_file_preview(path: Path) -> str | None:
    preview = path.read_text(encoding="utf-8", errors="ignore")[:MAX_RESPONSE_PREVIEW_CHARS]
    return preview.strip() or None
