from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd

from ..models import MetricEvent
from .metrics import METRIC_WINDOWS

LOGGER = logging.getLogger(__name__)


def find_metric_events(frame: pd.DataFrame, view_start: datetime, view_end: datetime) -> list[MetricEvent]:
    """表示期間内で各指標の最大イベントを抽出する。"""
    windowed = frame[(frame["observed_at"] >= view_start) & (frame["observed_at"] <= view_end)].copy()
    events: list[MetricEvent] = []
    for metric, hours in METRIC_WINDOWS.items():
        series = windowed[["observed_at", metric]].dropna()
        if series.empty:
            continue
        max_value = float(series[metric].max())
        matched = series[series[metric] == max_value]
        occurred_at = pd.Timestamp(matched["observed_at"].min()).to_pydatetime()
        duplicate_times = tuple(
            pd.Timestamp(value).to_pydatetime()
            for value in matched["observed_at"].tolist()
            if pd.Timestamp(value).to_pydatetime() != occurred_at
        )
        if duplicate_times:
            preview = [dt.isoformat(timespec="seconds") for dt in duplicate_times[:5]]
            LOGGER.info(
                "指標=%s 最大値=%s 採用時刻=%s 同値件数=%s 同値時刻例=%s",
                metric,
                max_value,
                occurred_at.isoformat(timespec="seconds"),
                len(duplicate_times),
                preview,
            )
        events.append(
            MetricEvent(
                metric=metric,
                window_hours=hours,
                occurred_at=occurred_at,
                value=max_value,
                duplicate_times=duplicate_times,
            )
        )
    return events
