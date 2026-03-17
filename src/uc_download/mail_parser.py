from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date


MAIL_BLOCK_START_PATTERN = re.compile(r"(?m)(?=^-{20,}\s*$)")
DOWNLOAD_URL_PATTERN = re.compile(r"https://ucrain\.i-ric\.info/download/\d+")
PERIOD_PATTERN = re.compile(r"データ期間[：:]\s*(\d{4}-\d{2}-\d{2})\s*[～~]\s*(\d{4}-\d{2}-\d{2})")


@dataclass(frozen=True)
class ParsedMailBody:
    """メール本文から抽出した最小情報。"""

    source_id: str
    download_url: str
    period_start: date
    period_end: date


def split_mail_bodies(text: str) -> list[str]:
    """連結されたメール本文を 1 件ずつへ分割する。"""
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return []

    chunks = [chunk.strip() for chunk in MAIL_BLOCK_START_PATTERN.split(normalized) if chunk.strip()]
    blocks = [chunk for chunk in chunks if "データ期間" in chunk or "ucrain.i-ric.info/download/" in chunk]
    if blocks:
        return blocks
    return [normalized]


def parse_mail_body(text: str) -> ParsedMailBody:
    """1 件のメール本文から URL と対象期間を抽出する。"""
    url_match = DOWNLOAD_URL_PATTERN.search(text)
    if url_match is None:
        raise ValueError("ダウンロード URL を抽出できませんでした。")

    period_match = PERIOD_PATTERN.search(text)
    if period_match is None:
        raise ValueError("データ期間を抽出できませんでした。")

    period_start = date.fromisoformat(period_match.group(1))
    period_end = date.fromisoformat(period_match.group(2))
    if period_end < period_start:
        raise ValueError("データ期間の終了日が開始日より前です。")

    download_url = url_match.group(0)
    tail = download_url.rstrip("/").rsplit("/", 1)[-1]
    source_id = f"{period_start:%Y%m%d}_{period_end:%Y%m%d}_{tail}"
    return ParsedMailBody(
        source_id=source_id,
        download_url=download_url,
        period_start=period_start,
        period_end=period_end,
    )
