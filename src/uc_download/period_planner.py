from __future__ import annotations

from datetime import date
from datetime import timedelta

from .models import RequestWindow


def build_request_windows(
    *,
    start_date: date,
    end_date: date,
    chunk_days: int,
) -> list[RequestWindow]:
    """指定期間を 1〜3 日単位の要求窓へ分割する。"""
    if chunk_days not in {1, 2, 3}:
        raise ValueError(f"chunk_days は 1, 2, 3 のいずれかである必要があります: {chunk_days}")
    if end_date < start_date:
        raise ValueError("終了日は開始日より前にできません。")

    windows: list[RequestWindow] = []
    current = start_date
    while current <= end_date:
        remaining = (end_date - current).days + 1
        days = min(chunk_days, remaining)
        finish = current + timedelta(days=days - 1)
        windows.append(RequestWindow(start_date=current, end_date=finish, days=days))
        current = finish + timedelta(days=1)
    return windows
