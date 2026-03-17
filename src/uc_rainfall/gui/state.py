from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..settings_store import load_settings

SERIES_MODE_LABELS = {
    "cell": "セル",
    "polygon_sum": "流域合計",
    "polygon_mean": "流域単純平均",
    "polygon_weighted_sum": "流域重み付き合計",
    "polygon_weighted_mean": "流域重み付き平均",
}
SERIES_MODE_BY_LABEL = {label: key for key, label in SERIES_MODE_LABELS.items()}
SPATIAL_METRIC_LABELS = {
    "1h": "1時間雨量",
    "3h": "3時間累加",
    "6h": "6時間累加",
    "12h": "12時間累加",
    "24h": "24時間累加",
    "48h": "48時間累加",
}
SPATIAL_METRIC_BY_LABEL = {label: key for key, label in SPATIAL_METRIC_LABELS.items()}


def _split_timestamp_parts(raw: str | None) -> tuple[str, str, str, str]:
    """ISO 文字列から 年 / 月 / 日 / 時刻 を取り出す。"""
    if not raw:
        return "", "", "", ""
    try:
        value = pd.Timestamp(raw)
    except Exception:
        return "", "", "", ""
    return value.strftime("%Y"), value.strftime("%m"), value.strftime("%d"), value.strftime("%H:%M")


@dataclass
class GuiState:
    """GUI 内で保持する主要状態。"""

    root: tk.Tk
    test_mode_default: bool = False
    cached_settings: dict[str, Any] = field(default_factory=load_settings)
    candidate_frame: pd.DataFrame = field(default_factory=pd.DataFrame)
    log_lines: list[str] = field(default_factory=list)
    widget_registry: dict[str, dict[str, Any]] = field(default_factory=dict)
    last_run_summary: dict[str, Any] = field(default_factory=dict)
    last_action_result: dict[str, Any] = field(default_factory=dict)
    last_processed_request_id: str | None = None

    def __post_init__(self) -> None:
        cached = self.cached_settings
        self.test_mode_var = tk.BooleanVar(value=self.test_mode_default)
        self.db_path_var = tk.StringVar(value=str(cached.get("db_path", "")))
        self.polygon_dir_var = tk.StringVar(value=str(cached.get("polygon_dir", "")))
        self.ingest_dataset_id_var = tk.StringVar(value=str(cached.get("dataset_id", "")))
        self.preferred_dataset_id_var = tk.StringVar(value="")
        self.polygon_name_var = tk.StringVar(value=str(cached.get("polygon_name", "")))
        self.series_mode_var = tk.StringVar(
            value=SERIES_MODE_LABELS.get(str(cached.get("series_mode", "cell")), "セル")
        )
        self.local_row_var = tk.StringVar(value="" if cached.get("local_row") is None else str(cached.get("local_row")))
        self.local_col_var = tk.StringVar(value="" if cached.get("local_col") is None else str(cached.get("local_col")))
        self.view_start_var = tk.StringVar(value=str(cached.get("view_start", "")))
        self.view_end_var = tk.StringVar(value=str(cached.get("view_end", "")))
        self.out_dir_var = tk.StringVar(value=str(cached.get("out_dir", "")))
        self.spatial_timestamp_var = tk.StringVar(
            value=str(cached.get("spatial_timestamp", cached.get("view_start", "")))
        )
        self.spatial_metric_var = tk.StringVar(
            value=SPATIAL_METRIC_LABELS.get(str(cached.get("spatial_metric", "1h")), "1時間雨量")
        )
        self.status_var = tk.StringVar(value="待機中")
        self.input_paths = [str(path) for path in cached.get("input_paths", []) if path]
        self.current_summary: dict[str, Any] = {}
        start_year, start_month, start_day, start_time = _split_timestamp_parts(cached.get("view_start"))
        end_year, end_month, end_day, end_time = _split_timestamp_parts(cached.get("view_end"))
        spatial_year, spatial_month, spatial_day, spatial_time = _split_timestamp_parts(
            cached.get("spatial_timestamp", cached.get("view_start"))
        )
        self.view_start_year_var = tk.StringVar(value=start_year)
        self.view_start_month_var = tk.StringVar(value=start_month)
        self.view_start_day_var = tk.StringVar(value=start_day)
        self.view_start_time_var = tk.StringVar(value=start_time)
        self.view_end_year_var = tk.StringVar(value=end_year)
        self.view_end_month_var = tk.StringVar(value=end_month)
        self.view_end_day_var = tk.StringVar(value=end_day)
        self.view_end_time_var = tk.StringVar(value=end_time)
        self.spatial_year_var = tk.StringVar(value=spatial_year)
        self.spatial_month_var = tk.StringVar(value=spatial_month)
        self.spatial_day_var = tk.StringVar(value=spatial_day)
        self.spatial_time_var = tk.StringVar(value=spatial_time)

    def get_series_mode(self) -> str:
        """表示ラベルから内部 series_mode を返す。"""
        return SERIES_MODE_BY_LABEL.get(self.series_mode_var.get(), "cell")

    def set_series_mode(self, mode: str) -> None:
        """内部 series_mode を表示ラベルへ反映する。"""
        self.series_mode_var.set(SERIES_MODE_LABELS.get(mode, "セル"))

    def get_spatial_metric(self) -> str:
        """面的可視化の内部 metric を返す。"""
        return SPATIAL_METRIC_BY_LABEL.get(self.spatial_metric_var.get(), "1h")
