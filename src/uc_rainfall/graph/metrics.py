from __future__ import annotations

import pandas as pd

METRIC_WINDOWS = {
    "1h": 1,
    "3h": 3,
    "6h": 6,
    "12h": 12,
    "24h": 24,
    "48h": 48,
}

TOTAL_WINDOW_HOURS = {
    "1h": 24,
    "3h": 48,
    "6h": 48,
    "12h": 72,
    "24h": 72,
    "48h": 96,
}

LABEL_INTERVAL_HOURS = {
    "1h": 1,
    "3h": 3,
    "6h": 3,
    "12h": 3,
    "24h": 3,
    "48h": 6,
}


def add_metric_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """1時間雨量から各時間幅の移動累加雨量列を追加する。"""
    result = frame.copy()
    result["rainfall_mm"] = pd.to_numeric(result["rainfall_mm"], errors="coerce")
    for metric, hours in METRIC_WINDOWS.items():
        result[metric] = result["rainfall_mm"].rolling(window=hours, min_periods=hours).sum()
    return result
