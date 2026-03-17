from __future__ import annotations

from datetime import datetime, time, timedelta

from .models import TimeSlot


def build_5day_slots(base_date) -> list[TimeSlot]:
    """基準日±2日の 120 スロットを作成する。"""
    start_day = base_date - timedelta(days=2)
    start_at = datetime.combine(start_day, time(hour=0, minute=0, second=0))
    slots: list[TimeSlot] = []
    for idx in range(120):
        observed_at = start_at + timedelta(hours=idx)
        slots.append(
            TimeSlot(
                index=idx,
                observed_at_jst=observed_at,
                relative_seconds=idx * 3600,
            )
        )
    return slots
