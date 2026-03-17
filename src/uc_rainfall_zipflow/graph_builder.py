from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from uc_rainfall.graph.chart_renderer import render_metric_chart

from .graph_renderer_reference import render_reference_chart

LOGGER = logging.getLogger("uc_rainfall_zipflow")

METRIC_WINDOWS = {
    "1h": 1,
    "3h": 3,
    "6h": 6,
    "12h": 12,
    "24h": 24,
    "48h": 48,
}


@dataclass(frozen=True)
class MetricPeak:
    metric: str
    occurred_at: pd.Timestamp
    value: float
    duplicates: tuple[pd.Timestamp, ...]


def build_metric_frame(observed_at: list, weighted_sum: list[float]) -> pd.DataFrame:
    """重み付き合計系列から指標列を生成する。"""
    frame = pd.DataFrame({"observed_at": observed_at, "rainfall_mm": weighted_sum})
    frame["quality"] = frame["rainfall_mm"].apply(lambda v: "missing" if pd.isna(v) else "normal")
    frame["rainfall_mm"] = frame["rainfall_mm"].fillna(0.0)
    for metric, hours in METRIC_WINDOWS.items():
        frame[metric] = frame["rainfall_mm"].rolling(window=hours, min_periods=hours).sum()
    return frame


def find_metric_peaks(frame: pd.DataFrame) -> list[MetricPeak]:
    """各指標の最大イベントを抽出する。"""
    peaks: list[MetricPeak] = []
    for metric in METRIC_WINDOWS:
        series = frame[["observed_at", metric]].dropna()
        if series.empty:
            raise ValueError(f"{metric} の最大イベントを抽出できません。")
        max_value = float(series[metric].max())
        matched = series[series[metric] == max_value]
        occurred_at = pd.Timestamp(matched["observed_at"].iloc[0])
        duplicates = tuple(pd.Timestamp(v) for v in matched["observed_at"].iloc[1:].tolist())
        if duplicates:
            LOGGER.warning(
                "同値最大: metric=%s value=%.3f 採用=%s 非採用=%s",
                metric,
                max_value,
                occurred_at.strftime("%Y-%m-%d %H:%M:%S"),
                [item.strftime("%Y-%m-%d %H:%M:%S") for item in duplicates],
            )
        peaks.append(MetricPeak(metric=metric, occurred_at=occurred_at, value=max_value, duplicates=duplicates))
    return peaks


def render_region_plots(
    *,
    frame: pd.DataFrame,
    peaks: list[MetricPeak],
    region_key: str,
    region_label: str,
    output_dir: Path,
) -> list[Path]:
    """既存スタイルで領域の指標グラフを保存する。"""
    saved: list[Path] = []
    for peak in peaks:
        stamp = peak.occurred_at.strftime("%Y%m%d%H")
        out = output_dir / region_key / f"{region_key}_{peak.metric}_{stamp}.png"
        title = f"{region_label} 重み付き合計雨量 {peak.metric} 最大={peak.value:.2f} mm"
        render_metric_chart(
            frame,
            metric=peak.metric,
            event_time=peak.occurred_at.to_pydatetime(),
            output_path=out,
            title=title,
        )
        saved.append(out)
    return saved


def render_region_plots_reference(
    *,
    frame: pd.DataFrame,
    region_key: str,
    region_label: str,
    output_dir: Path,
    base_date: date,
) -> list[Path]:
    """参考画像寄せスタイルで領域ごとに1枚の全期間グラフを保存する。"""
    out = output_dir / region_key / f"{region_key}_{base_date:%Y%m%d}_overview.png"
    title = f"{region_label} 重み付き合計雨量"
    render_reference_chart(
        frame,
        output_path=out,
        title=title,
        badge_date=base_date,
    )
    return [out]
