from __future__ import annotations

from datetime import datetime, time, timedelta

from .models import TimeSlot


def build_hourly_slots(*, window_start: datetime, window_end: datetime) -> list[TimeSlot]:
    """期間内（両端含む）の1時間スロットを作成する。"""
    if window_end < window_start:
        raise ValueError("期間指定が不正です（end < start）。")
    span_hours = int((window_end - window_start).total_seconds() // 3600) + 1
    slots: list[TimeSlot] = []
    for idx in range(span_hours):
        observed_at = window_start + timedelta(hours=idx)
        slots.append(
            TimeSlot(
                index=idx,
                observed_at_jst=observed_at,
                relative_seconds=idx * 3600,
            )
        )
    return slots


def build_5day_slots(base_date) -> list[TimeSlot]:
    """基準日±2日の 120 スロットを作成する。"""
    start_day = base_date - timedelta(days=2)
    start_at = datetime.combine(start_day, time(hour=0, minute=0, second=0))
    end_at = datetime.combine(base_date + timedelta(days=2), time(hour=23, minute=0, second=0))
    return build_hourly_slots(window_start=start_at, window_end=end_at)
