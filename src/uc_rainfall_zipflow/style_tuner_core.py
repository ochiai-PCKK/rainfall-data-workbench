# pyright: reportArgumentType=false, reportGeneralTypeIssues=false
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .style_profile import GraphStyleProfile, default_style_profile


def profile_from_plain(values: dict[str, object]) -> GraphStyleProfile:
    base = asdict(default_style_profile())
    payload: dict[str, object] = {}
    for key, default in base.items():
        value = values[key]
        if isinstance(default, bool):
            payload[key] = bool(value)
        elif isinstance(default, int):
            payload[key] = int(float(value))
        elif isinstance(default, float):
            payload[key] = float(value)
        else:
            payload[key] = value
    return GraphStyleProfile(**payload)


def read_timeseries_csv(path: Path, value_kind: str) -> pd.DataFrame:
    src = pd.read_csv(path, encoding="utf-8-sig")
    required = {"observed_at_jst", "weighted_sum_mm", "weighted_mean_mm"}
    missing = sorted(required - set(src.columns))
    if missing:
        raise ValueError(f"CSV 必須列が不足しています: {missing}")
    col = "weighted_sum_mm" if value_kind == "sum" else "weighted_mean_mm"
    frame = pd.DataFrame({"observed_at": pd.to_datetime(src["observed_at_jst"]), "rainfall_mm": src[col]})
    return normalize_input_frame(frame)


def build_synthetic_frame(value_kind: str) -> pd.DataFrame:
    start = datetime.combine(datetime.now().date() - timedelta(days=2), time(hour=0))
    observed_at = [start + timedelta(hours=i) for i in range(120)]
    values: list[float] = []
    for i in range(120):
        x = i / 120.0
        peak1 = 45.0 * np.exp(-((x - 0.35) ** 2) / 0.0028)
        peak2 = 30.0 * np.exp(-((x - 0.72) ** 2) / 0.0048)
        base = 2.0 + 4.0 * np.sin(i / 8.5) ** 2
        values.append(float(max(0.0, base + peak1 + peak2)))
    if value_kind == "mean":
        values = [v * 0.18 for v in values]
    return pd.DataFrame({"observed_at": observed_at, "rainfall_mm": values})


def normalize_input_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"observed_at", "rainfall_mm"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"スタイル調整データの必須列が不足しています: {missing}")
    out = frame.copy()
    out["observed_at"] = pd.to_datetime(out["observed_at"], errors="coerce")
    out["rainfall_mm"] = pd.to_numeric(out["rainfall_mm"], errors="coerce")
    if out["observed_at"].isna().any():
        raise ValueError("observed_at に解釈できない日時が含まれます。")
    if out["rainfall_mm"].isna().any():
        raise ValueError("rainfall_mm に数値以外が含まれます。")
    out = out.sort_values("observed_at").reset_index(drop=True)
    return out


def slice_preview_window(window_full: pd.DataFrame, span: str) -> pd.DataFrame:
    span_hours = 72 if span == "3d" else 120
    if len(window_full) < span_hours:
        raise ValueError(
            f"{span} プレビューに必要なデータが不足しています: "
            f"required={span_hours} actual={len(window_full)}"
        )
    start_idx = max(0, (len(window_full) - span_hours) // 2)
    end_idx = start_idx + span_hours
    return window_full.iloc[start_idx:end_idx].copy()
