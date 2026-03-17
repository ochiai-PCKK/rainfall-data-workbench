from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import MultipleLocator

_FIG_BG = "#ffffff"
_BAR_COLOR = "#00BFFF"
_LINE_COLOR = "#0000cc"


def _jst_date_text(value: date) -> str:
    return value.strftime("%Y.%m.%d")


def _ceil_nice(value: float, step: float) -> float:
    if value <= 0:
        return step
    return float(np.ceil(value / step) * step)


def _axis_steps(top: float, *, base_major: float, base_minor: float) -> tuple[float, float]:
    if top <= base_major * 10:
        return base_major, base_minor
    major = _ceil_nice(top / 8.0, base_major)
    minor = major / 5.0
    return major, minor


def render_reference_chart(
    frame: pd.DataFrame,
    *,
    output_path: str | Path,
    title: str,
    badge_date: date | None = None,
) -> Path:
    """指示書準拠の体裁で棒+累加線グラフを1枚描画する。"""
    if frame.empty:
        raise ValueError("描画対象データがありません。")

    window = frame[["observed_at", "rainfall_mm"]].copy()
    window["observed_at"] = pd.to_datetime(window["observed_at"])
    window = window.sort_values("observed_at")
    idx = pd.date_range(window["observed_at"].min().floor("h"), window["observed_at"].max().floor("h"), freq="h")
    window = window.set_index("observed_at").reindex(idx).rename_axis("observed_at").reset_index()
    window["rainfall_mm"] = pd.to_numeric(window["rainfall_mm"], errors="coerce").fillna(0.0)
    window["cumulative_mm"] = window["rainfall_mm"].cumsum()

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    fig = plt.figure(figsize=(10, 5), dpi=120)
    grid = fig.add_gridspec(nrows=2, ncols=1, height_ratios=[14, 3], hspace=0.0)
    ax1 = fig.add_subplot(grid[0])
    ax_tbl = fig.add_subplot(grid[1], sharex=ax1)
    fig.patch.set_facecolor(_FIG_BG)
    ax1.set_facecolor(_FIG_BG)
    ax_tbl.set_facecolor("none")
    ax2 = ax1.twinx()

    times = window["observed_at"]
    xmin = pd.Timestamp(times.min()) - pd.Timedelta(hours=0.5)
    xmax = pd.Timestamp(times.max()) + pd.Timedelta(hours=0.5)
    ax1.bar(
        times,
        window["rainfall_mm"],
        width=timedelta(hours=0.96),
        color=_BAR_COLOR,
        edgecolor="black",
        linewidth=0.4,
        zorder=3,
    )
    ax2.plot(times, window["cumulative_mm"], color=_LINE_COLOR, linewidth=2.7, zorder=4)

    # Y axis
    ax1.set_ylabel("時刻雨量（mm/hr）")
    ax2.set_ylabel("累加雨量（mm）", rotation=270, labelpad=16)
    left_max = float(window["rainfall_mm"].max())
    right_max = float(window["cumulative_mm"].max())
    left_top = _ceil_nice(left_max * 1.1, 10.0)
    right_top = _ceil_nice(right_max * 1.1, 50.0)
    left_major, left_minor = _axis_steps(left_top, base_major=10.0, base_minor=2.0)
    right_major, right_minor = _axis_steps(right_top, base_major=50.0, base_minor=10.0)
    ax1.set_ylim(0, left_top)
    ax2.set_ylim(0, right_top)
    ax1.yaxis.set_major_locator(MultipleLocator(left_major))
    ax1.yaxis.set_minor_locator(MultipleLocator(left_minor))
    ax2.yaxis.set_major_locator(MultipleLocator(right_major))
    ax2.yaxis.set_minor_locator(MultipleLocator(right_minor))
    ax1.grid(axis="y", which="major", linestyle="--", color="gray", linewidth=0.6, alpha=0.5)
    ax1.set_xlim(xmin, xmax)

    # X軸は下段専用エリアで描画するため、本体は非表示
    ax1.tick_params(axis="x", which="both", labelbottom=False, bottom=False)

    # 垂直線: 日付境界のみ
    start_day = pd.Timestamp(times.min()).normalize()
    end_day = pd.Timestamp(times.max()).normalize() + pd.Timedelta(days=1)
    day_boundaries = pd.date_range(start_day, end_day, freq="D")
    for boundary in day_boundaries[1:-1]:
        ax1.axvline(boundary, color="#555555", linewidth=0.8, linestyle=":", zorder=1)

    # 下段の表組み軸（2行: 上=時刻、下=日付）
    ax_tbl.set_ylim(0.0, 2.0)
    ax_tbl.set_yticks([])
    ax_tbl.set_xlim(xmin, xmax)
    ax_tbl.tick_params(axis="x", which="both", bottom=False, labelbottom=False)
    # 左の二重線防止: 端の境界線は描かず、日付境界の内部線のみ描画
    for boundary in day_boundaries[1:-1]:
        ax_tbl.vlines(boundary, ymin=0.0, ymax=2.0, colors="black", linewidth=0.8)
    # テーブル左右端の閉じ線
    ax_tbl.vlines([xmin, xmax], ymin=0.0, ymax=2.0, colors="black", linewidth=0.8, clip_on=False)

    ax_tbl.spines["left"].set_visible(False)
    ax_tbl.spines["right"].set_visible(False)
    ax_tbl.spines["top"].set_visible(False)
    ax_tbl.spines["bottom"].set_visible(False)

    # 時刻ラベル (3, 9, 15, 21)
    all_hours = pd.date_range(start_day, end_day, freq="h")
    hour_ticks = [t for t in all_hours if t.hour in (3, 9, 15, 21) and xmin <= t <= xmax]
    for tick in hour_ticks:
        ax_tbl.text(tick, 1.5, f"{tick.hour}", ha="center", va="center", fontsize=8, color="black")

    # 日付ラベル（日の中央）
    day_starts = pd.date_range(start_day, pd.Timestamp(times.max()).normalize(), freq="D")
    for day_start in day_starts:
        center = day_start + pd.Timedelta(hours=12)
        if xmin <= center <= xmax:
            ax_tbl.text(
                center,
                0.5,
                day_start.strftime("%Y.%m.%d"),
                ha="center",
                va="center",
                fontsize=8,
                color="black",
            )

    for spine in ax1.spines.values():
        spine.set_linewidth(0.8)
        spine.set_color("black")
    for side in ("left", "right", "top", "bottom"):
        ax2.spines[side].set_visible(False)

    badge = badge_date or pd.Timestamp(times.iloc[0]).date()
    ax1.text(
        0.02,
        0.95,
        _jst_date_text(badge),
        transform=ax1.transAxes,
        ha="left",
        va="top",
        color="white",
        fontsize=10,
        bbox={"facecolor": "black", "edgecolor": "white", "boxstyle": "square,pad=0.2"},
    )

    ax1.set_title(title, fontsize=10, pad=8)
    fig.subplots_adjust(left=0.08, right=0.92, top=0.92, bottom=0.12, hspace=0.0)
    fig.savefig(out, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out
