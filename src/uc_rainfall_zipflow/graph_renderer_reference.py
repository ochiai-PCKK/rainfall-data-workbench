# pyright: reportArgumentType=false, reportCallIssue=false, reportAttributeAccessIssue=false, reportReturnType=false, reportGeneralTypeIssues=false
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.ticker import FixedLocator, MultipleLocator

from .style_profile import GraphStyleProfile, default_style_profile

_FIG_BG = "#ffffff"
_BAR_COLOR = "#00BFFF"
_LINE_COLOR = "#0000cc"
_DEFAULT_LEFT_TOP = 60.0
_DEFAULT_RIGHT_TOP = 300.0


def _resolve_tick_hours(values: list[int]) -> list[int]:
    unique_sorted = sorted({int(v) for v in values if 0 <= int(v) <= 23})
    return unique_sorted if unique_sorted else [6, 12, 18]


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


def _resolve_common_major_intervals(*, left_top: float, right_top: float) -> int:
    left_major, _left_minor = _axis_steps(left_top, base_major=10.0, base_minor=2.0)
    right_major, _right_minor = _axis_steps(right_top, base_major=50.0, base_minor=10.0)
    left_intervals = max(1, int(np.ceil(left_top / left_major)))
    right_intervals = max(1, int(np.ceil(right_top / right_major)))
    return max(3, min(8, min(left_intervals, right_intervals)))


def _align_axis_to_common_intervals(*, top: float, intervals: int, base_major: float) -> tuple[float, float]:
    major = _ceil_nice(top / float(intervals), base_major)
    aligned_top = major * float(intervals)
    return aligned_top, major


def compute_axis_tops(
    *,
    left_max: float,
    right_max: float,
    left_top_default: float = _DEFAULT_LEFT_TOP,
    right_top_default: float = _DEFAULT_RIGHT_TOP,
) -> tuple[float, float]:
    """左右軸の表示上限（0始まり）を固定値で返す。"""
    _ = left_max, right_max
    return float(left_top_default), float(right_top_default)


def resolve_axis_tops(
    window: pd.DataFrame,
    *,
    left_top_default: float = _DEFAULT_LEFT_TOP,
    right_top_default: float = _DEFAULT_RIGHT_TOP,
) -> tuple[float, float]:
    """描画ウィンドウから左右軸の上限を自動決定する。"""
    left_max = float(window["rainfall_mm"].max())
    right_max = float(window["cumulative_mm"].max())
    return compute_axis_tops(
        left_max=left_max,
        right_max=right_max,
        left_top_default=left_top_default,
        right_top_default=right_top_default,
    )


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
    left_top: float | None = None,
    right_top: float | None = None,
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
    left_margin_hours = max(0.0, float(cfg.x_margin_hours_left))
    right_margin_hours = max(0.0, float(cfg.x_margin_hours_right))
    xmin = pd.Timestamp(times.min()) - pd.Timedelta(hours=left_margin_hours)
    xmax = pd.Timestamp(times.max()) + pd.Timedelta(hours=right_margin_hours)
    ax1.bar(
        times,
        window["rainfall_mm"],
        width=timedelta(hours=cfg.bar_width_hours),
        color=_BAR_COLOR,
        edgecolor="black",
        linewidth=cfg.bar_edge_linewidth,
        zorder=3,
    )
    # 累加線は棒グラフの外縁（左右端）まで届くように、x を半時間ずらした端点列で描画する。
    cum_x = [xmin] + [pd.Timestamp(t) + pd.Timedelta(hours=0.5) for t in times]
    cum_y = [0.0] + window["cumulative_mm"].astype(float).tolist()
    ax2.plot(cum_x, cum_y, color=_LINE_COLOR, linewidth=cfg.line_width, zorder=4)

    ax1.set_ylabel("時刻雨量（mm/hr）", fontsize=cfg.axis_label_fontsize, labelpad=cfg.y1_label_pad)
    ax2.set_ylabel("累加雨量（mm）", rotation=270, labelpad=cfg.y2_label_pad, fontsize=cfg.axis_label_fontsize)
    auto_left_top, auto_right_top = resolve_axis_tops(
        window,
        left_top_default=cfg.left_axis_top,
        right_top_default=cfg.right_axis_top,
    )
    left_top = auto_left_top if left_top is None else float(left_top)
    right_top = auto_right_top if right_top is None else float(right_top)
    # 軸上限はスタイル設定値を優先し、主目盛数もスタイルで調整可能にする。
    left_major_tick_count = max(2, int(cfg.left_major_tick_count))
    right_major_tick_count = max(2, int(cfg.right_major_tick_count))
    left_major_tick_step = float(cfg.left_major_tick_step)
    right_major_tick_step = float(cfg.right_major_tick_step)
    if left_major_tick_step > 0:
        left_ticks = np.arange(0.0, left_top + left_major_tick_step * 0.5, left_major_tick_step).tolist()
        left_minor = left_major_tick_step / 5.0
    else:
        left_ticks = np.linspace(0.0, left_top, left_major_tick_count).tolist()
        left_minor = left_top / float((left_major_tick_count - 1) * 5)
    if right_major_tick_step > 0:
        right_ticks = np.arange(0.0, right_top + right_major_tick_step * 0.5, right_major_tick_step).tolist()
        right_minor = right_major_tick_step / 5.0
    else:
        right_ticks = np.linspace(0.0, right_top, right_major_tick_count).tolist()
        right_minor = right_top / float((right_major_tick_count - 1) * 5)
    left_top_aligned = left_top
    right_top_aligned = right_top
    ax1.set_ylim(0, left_top_aligned)
    ax2.set_ylim(0, right_top_aligned)
    ax1.yaxis.set_major_locator(FixedLocator(left_ticks))
    ax2.yaxis.set_major_locator(FixedLocator(right_ticks))
    if left_minor > 0:
        ax1.yaxis.set_minor_locator(MultipleLocator(left_minor))
    if right_minor > 0:
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
    tick_hours = _resolve_tick_hours(cfg.x_tick_hours_list)
    hour_ticks = [t for t in all_hours if t.hour in tick_hours and xmin <= t <= xmax]
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
    date_label_format = cfg.x_date_label_format or "%Y.%m.%d"
    for day_start in day_starts:
        center = day_start + pd.Timedelta(hours=12)
        if xmin <= center <= xmax:
            ax_tbl.text(
                center,
                cfg.table_row_bottom_y,
                day_start.strftime(date_label_format),
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
    left_top: float | None = None,
    right_top: float | None = None,
) -> Path:
    """指示書準拠の体裁で棒+累加線グラフを1枚描画する。"""
    window = prepare_reference_window(frame)
    fig = draw_reference_chart(
        window=window,
        title=title,
        style=style,
        left_top=left_top,
        right_top=right_top,
        figure=None,
    )

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out
