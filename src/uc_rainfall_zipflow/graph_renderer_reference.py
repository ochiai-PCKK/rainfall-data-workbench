from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.ticker import MultipleLocator

from .style_profile import GraphStyleProfile, default_style_profile

_FIG_BG = "#ffffff"
_BAR_COLOR = "#00BFFF"
_LINE_COLOR = "#0000cc"


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


def prepare_reference_window(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        raise ValueError("描画対象データがありません。")
    window = frame[["observed_at", "rainfall_mm"]].copy()
    window["observed_at"] = pd.to_datetime(window["observed_at"])
    window = window.sort_values("observed_at")
    idx = pd.date_range(window["observed_at"].min().floor("h"), window["observed_at"].max().floor("h"), freq="h")
    window = window.set_index("observed_at").reindex(idx).rename_axis("observed_at").reset_index()
    window["rainfall_mm"] = pd.to_numeric(window["rainfall_mm"], errors="coerce").fillna(0.0)
    window["cumulative_mm"] = window["rainfall_mm"].cumsum()
    return window


def draw_reference_chart(
    *,
    window: pd.DataFrame,
    title: str,
    style: GraphStyleProfile | None,
    figure: Figure | None = None,
) -> Figure:
    cfg = style or default_style_profile()
    fig = figure or Figure(figsize=(cfg.fig_width, cfg.fig_height), dpi=cfg.dpi)
    fig.clear()
    fig.set_size_inches(cfg.fig_width, cfg.fig_height, forward=True)
    fig.set_dpi(cfg.dpi)
    fig.patch.set_facecolor(_FIG_BG)

    grid = fig.add_gridspec(nrows=2, ncols=1, height_ratios=[14, cfg.table_height_ratio], hspace=cfg.hspace)
    ax1 = fig.add_subplot(grid[0])
    ax_tbl = fig.add_subplot(grid[1], sharex=ax1)
    ax1.set_facecolor(_FIG_BG)
    ax_tbl.set_facecolor("none")
    ax2 = ax1.twinx()

    times = window["observed_at"]
    xmin = pd.Timestamp(times.min()) - pd.Timedelta(hours=0.5)
    xmax = pd.Timestamp(times.max()) + pd.Timedelta(hours=0.5)
    ax1.bar(
        times,
        window["rainfall_mm"],
        width=timedelta(hours=cfg.bar_width_hours),
        color=_BAR_COLOR,
        edgecolor="black",
        linewidth=cfg.bar_edge_linewidth,
        zorder=3,
    )
    ax2.plot(times, window["cumulative_mm"], color=_LINE_COLOR, linewidth=cfg.line_width, zorder=4)

    ax1.set_ylabel("時刻雨量（mm/hr）", fontsize=cfg.axis_label_fontsize, labelpad=cfg.y1_label_pad)
    ax2.set_ylabel("累加雨量（mm）", rotation=270, labelpad=cfg.y2_label_pad, fontsize=cfg.axis_label_fontsize)
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
    if cfg.grid_y_visible:
        ax1.grid(
            axis="y",
            which="major",
            linestyle="--",
            color=cfg.grid_y_color,
            linewidth=cfg.grid_y_linewidth,
            alpha=cfg.grid_y_alpha,
        )
    ax1.set_xlim(xmin, xmax)

    ax1.tick_params(axis="x", which="both", labelbottom=False, bottom=False, labelsize=cfg.tick_fontsize)
    ax1.tick_params(axis="y", which="both", labelsize=cfg.tick_fontsize, pad=cfg.y_tick_pad)
    ax2.tick_params(axis="y", which="both", labelsize=cfg.tick_fontsize, pad=cfg.y_tick_pad)

    start_day = pd.Timestamp(times.min()).normalize()
    end_day = pd.Timestamp(times.max()).normalize() + pd.Timedelta(days=1)
    day_boundaries = pd.date_range(start_day, end_day, freq="D")
    if cfg.grid_x_visible:
        for boundary in day_boundaries[1:-1]:
            ax1.axvline(
                boundary,
                color=cfg.grid_x_color,
                linewidth=cfg.grid_x_linewidth,
                linestyle=":",
                alpha=cfg.grid_x_alpha,
                zorder=1,
            )

    ax_tbl.set_ylim(0.0, 2.0)
    ax_tbl.set_yticks([])
    ax_tbl.set_xlim(xmin, xmax)
    ax_tbl.tick_params(axis="x", which="both", bottom=False, labelbottom=False)
    for boundary in day_boundaries[1:-1]:
        ax_tbl.vlines(boundary, ymin=0.0, ymax=2.0, colors="black", linewidth=cfg.table_vertical_linewidth)
    ax_tbl.vlines(
        [xmin, xmax],
        ymin=0.0,
        ymax=2.0,
        colors="black",
        linewidth=cfg.table_vertical_linewidth,
        clip_on=False,
    )

    ax_tbl.spines["left"].set_visible(False)
    ax_tbl.spines["right"].set_visible(False)
    ax_tbl.spines["top"].set_visible(False)
    ax_tbl.spines["bottom"].set_visible(False)

    all_hours = pd.date_range(start_day, end_day, freq="h")
    hour_ticks = [t for t in all_hours if t.hour in (3, 9, 15, 21) and xmin <= t <= xmax]
    for tick in hour_ticks:
        ax_tbl.text(
            tick,
            cfg.table_row_top_y,
            f"{tick.hour}",
            ha="center",
            va="center",
            fontsize=cfg.tick_fontsize,
            color="black",
        )

    day_starts = pd.date_range(start_day, pd.Timestamp(times.max()).normalize(), freq="D")
    for day_start in day_starts:
        center = day_start + pd.Timedelta(hours=12)
        if xmin <= center <= xmax:
            ax_tbl.text(
                center,
                cfg.table_row_bottom_y,
                day_start.strftime("%Y.%m.%d"),
                ha="center",
                va="center",
                fontsize=cfg.tick_fontsize,
                color="black",
            )

    for spine in ax1.spines.values():
        spine.set_linewidth(0.8)
        spine.set_color("black")
    for side in ("left", "right", "top", "bottom"):
        ax2.spines[side].set_visible(False)

    ax1.set_title(title, fontsize=cfg.title_fontsize, pad=cfg.title_pad)
    fig.subplots_adjust(left=cfg.left, right=cfg.right, top=cfg.top, bottom=cfg.bottom, hspace=cfg.hspace)
    return fig


def render_reference_chart(
    frame: pd.DataFrame,
    *,
    output_path: str | Path,
    title: str,
    style: GraphStyleProfile | None = None,
) -> Path:
    """指示書準拠の体裁で棒+累加線グラフを1枚描画する。"""
    window = prepare_reference_window(frame)
    fig = draw_reference_chart(window=window, title=title, style=style, figure=None)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out
