from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import math
import platform as _platform

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from .metrics import LABEL_INTERVAL_HOURS, METRIC_WINDOWS, TOTAL_WINDOW_HOURS

_os_name = _platform.system()
if _os_name == "Windows":
    matplotlib.rcParams["font.family"] = ["MS Gothic", "Yu Gothic", "Meiryo", "sans-serif"]
elif _os_name == "Darwin":
    matplotlib.rcParams["font.family"] = ["Hiragino Sans", "Hiragino Kaku Gothic Pro", "sans-serif"]
else:
    matplotlib.rcParams["font.family"] = ["IPAGothic", "IPAPGothic", "Noto Sans CJK JP", "sans-serif"]
matplotlib.rcParams["axes.unicode_minus"] = False

_BAR_COLOR = "#2E6EB5"
_LINE_COLOR = "#E74C3C"
_PEAK_LINE_COLOR = "#2ECC71"
_MISSING_COLOR = "#CCCCCC"


def _compute_before_after(metric: str) -> tuple[timedelta, timedelta]:
    """指標時間幅に応じてピーク前後の切り出し時間を計算する。"""
    metric_hours = METRIC_WINDOWS[metric]
    total_hours = TOTAL_WINDOW_HOURS[metric]
    ratio = 1.0 + 2.0 * (metric_hours - 1) / 47.0
    before_hours = round(total_hours * ratio / (ratio + 1.0))
    after_hours = total_hours - before_hours
    return timedelta(hours=before_hours), timedelta(hours=after_hours)


def _nice_step(max_value: float, n_ticks: int) -> float:
    """軸目盛に使う、きりの良いステップ値を返す。"""
    if max_value <= 0 or n_ticks <= 1:
        return max(max_value, 1.0)
    raw = max_value / (n_ticks - 1)
    magnitude = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    normalized = raw / magnitude
    if normalized <= 1:
        nice = 1
    elif normalized <= 2:
        nice = 2
    elif normalized <= 5:
        nice = 5
    else:
        nice = 10
    return nice * magnitude


def render_metric_chart(
    frame: pd.DataFrame,
    *,
    metric: str,
    event_time,
    output_path: str | Path,
    title: str,
) -> Path:
    """最大イベント周辺の降雨グラフを描画して PNG 保存する。"""
    before, after = _compute_before_after(metric)
    start = event_time - before
    end = event_time + after

    window = frame[(frame["observed_at"] >= start) & (frame["observed_at"] <= end)].copy()
    if window.empty:
        raise ValueError(f"イベント {event_time} 周辺のデータがありません: metric={metric}")

    window["rainfall_mm"] = pd.to_numeric(window["rainfall_mm"], errors="coerce").fillna(0.0)
    window["cumulative_mm"] = window["rainfall_mm"].cumsum()
    if "quality" in window.columns:
        window["quality"] = window["quality"].fillna("normal")
    else:
        window["quality"] = "normal"

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    fig, ax1 = plt.subplots(figsize=(14, 6))
    times = window["observed_at"]
    rainfall = window["rainfall_mm"].to_numpy()
    cumulative = window["cumulative_mm"].to_numpy()

    missing_drawn = False
    half_h = timedelta(minutes=30)
    for row in window.itertuples(index=False):
        if str(row.quality) == "missing":
            ax1.axvspan(
                row.observed_at - half_h,
                row.observed_at + half_h,
                color=_MISSING_COLOR,
                alpha=0.3,
                zorder=0,
                label="欠測" if not missing_drawn else None,
            )
            missing_drawn = True

    ax2 = ax1.twinx()
    ax1.bar(
        times,
        rainfall,
        width=timedelta(hours=1),
        color=_BAR_COLOR,
        edgecolor="black",
        linewidth=0.5,
        alpha=0.85,
        label="時間雨量",
        zorder=2,
    )
    ax2.plot(times, cumulative, color=_LINE_COLOR, linewidth=2.0, label="累加雨量", zorder=3)
    ax1.axvline(event_time, color=_PEAK_LINE_COLOR, linestyle="--", linewidth=1.5, label="ピーク時刻", zorder=4)

    max_rainfall = float(max(rainfall)) if len(rainfall) > 0 else 1.0
    max_cumulative = float(max(cumulative)) if len(cumulative) > 0 else 1.0
    n_divisions = 6
    left_step = _nice_step(max_rainfall * 1.3, n_divisions + 1)
    right_step = _nice_step(max_cumulative * 1.1, n_divisions + 1)
    left_ticks = [left_step * i for i in range(n_divisions + 1)]
    right_ticks = [right_step * i for i in range(n_divisions + 1)]
    ax1.set_yticks(left_ticks)
    ax1.set_ylim(0, left_ticks[-1])
    ax2.set_yticks(right_ticks)
    ax2.set_ylim(0, right_ticks[-1])

    ax1.set_title(title, fontsize=14, fontweight="bold", pad=12)
    ax1.set_xlabel("観測時刻 (JST)")
    ax1.set_ylabel("時間雨量 (mm)", color=_BAR_COLOR, fontsize=11)
    ax1.tick_params(axis="y", labelcolor=_BAR_COLOR)
    ax2.set_ylabel("累加雨量 (mm)", color=_LINE_COLOR, fontsize=11)
    ax2.tick_params(axis="y", labelcolor=_LINE_COLOR)

    ax1.xaxis.set_major_locator(mdates.HourLocator(interval=LABEL_INTERVAL_HOURS[metric]))
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d\n%H:%M"))
    plt.setp(ax1.xaxis.get_majorticklabels(), rotation=0, ha="center", fontsize=8)

    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(handles1 + handles2, labels1 + labels2, loc="upper left", fontsize=9)
    ax1.grid(axis="y", alpha=0.3)

    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output
