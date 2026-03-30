from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import matplotlib.dates as mdates
import pandas as pd
import pytest

from uc_rainfall_zipflow.application import _build_reference_axis_tops_for_run
from uc_rainfall_zipflow.excel_application import _build_excel_axis_tops, _ExcelRenderJob
from uc_rainfall_zipflow.graph_builder import build_metric_frame, render_region_plots_reference
from uc_rainfall_zipflow.graph_renderer_reference import (
    compute_axis_tops,
    draw_reference_chart,
    prepare_reference_window,
)
from uc_rainfall_zipflow.style_profile import GraphStyleProfile


def _build_120h_frame(base_date: date, *, inside_peak: float, outside_peak: float) -> pd.DataFrame:
    start = datetime.combine(base_date - timedelta(days=2), datetime.min.time())
    observed_at = [start + timedelta(hours=i) for i in range(120)]
    rainfall = [0.0] * 120
    # 3日窓(基準日±1日)外にだけ大きい値を置く
    rainfall[0] = outside_peak
    # 3日窓内にピークを置く
    in_window_index = 60
    rainfall[in_window_index] = inside_peak
    return build_metric_frame(observed_at=observed_at, weighted_sum=rainfall)


def test_render_region_plots_reference_passes_axis_tops(monkeypatch, tmp_path: Path) -> None:
    base_date = date(2024, 1, 3)
    observed_at = [datetime(2024, 1, 1) + timedelta(hours=i) for i in range(120)]
    rainfall = [0.0] * 120
    frame_sum = build_metric_frame(observed_at=observed_at, weighted_sum=rainfall)
    frame_mean = build_metric_frame(observed_at=observed_at, weighted_sum=rainfall)

    captured: list[tuple[float | None, float | None]] = []

    def _fake_render_reference_chart(
        frame,
        *,
        output_path,
        title,
        style=None,
        left_top=None,
        right_top=None,
    ):
        captured.append((left_top, right_top))
        return Path(output_path)

    monkeypatch.setattr("uc_rainfall_zipflow.graph_builder.render_reference_chart", _fake_render_reference_chart)
    monkeypatch.setattr("uc_rainfall_zipflow.graph_builder._resolve_output_path", lambda path, on_conflict: path)

    render_region_plots_reference(
        frame_sum=frame_sum,
        frame_mean=frame_mean,
        region_key="nishiyoke",
        region_label="西除川",
        output_dir=tmp_path,
        base_date=base_date,
        graph_spans=("5d",),
        ref_graph_kinds=("sum", "mean"),
        export_svg=False,
        axis_tops={("5d", "sum"): (40.0, 200.0), ("5d", "mean"): (20.0, 100.0)},
    )

    assert captured == [(40.0, 200.0), (20.0, 100.0)]


def test_build_excel_axis_tops_uses_render_span_window_only() -> None:
    base_date = date(2024, 1, 3)
    frame_a = _build_120h_frame(base_date, inside_peak=10.0, outside_peak=1000.0)
    frame_b = _build_120h_frame(base_date, inside_peak=20.0, outside_peak=900.0)

    jobs = [
        _ExcelRenderJob(
            source_path=Path("a.xlsx"),
            source_alias="a.xlsx",
            sheet_name="2024.01.03",
            base_date=base_date,
            effective_base_date=base_date,
            frame_sum=frame_a,
            frame_mean=frame_a,
        ),
        _ExcelRenderJob(
            source_path=Path("b.xlsx"),
            source_alias="b.xlsx",
            sheet_name="2024.01.04",
            base_date=date(2024, 1, 4),
            effective_base_date=date(2024, 1, 4),
            frame_sum=frame_b,
            frame_mean=frame_b,
        ),
    ]

    axis_tops = _build_excel_axis_tops(
        jobs=jobs,
        render_span="3d",
        ref_graph_kinds=("sum",),
        left_top_default=60.0,
        right_top_default=300.0,
    )

    left_top, right_top = axis_tops[("3d", "sum")]
    assert left_top == 60.0
    assert right_top == 300.0


def test_compute_axis_tops_uses_nice_ceil_rule() -> None:
    left_top, right_top = compute_axis_tops(left_max=20.0, right_max=220.0)
    assert left_top == 60.0
    assert right_top == 300.0


def test_build_reference_axis_tops_for_run_returns_span_kind_keys() -> None:
    base_date = date(2024, 1, 3)
    observed_at = [datetime(2024, 1, 1) + timedelta(hours=i) for i in range(120)]
    rainfall_sum = [0.0] * 120
    rainfall_mean = [0.0] * 120
    rainfall_sum[48] = 21.0
    rainfall_mean[48] = 8.0
    frame_sum = build_metric_frame(observed_at=observed_at, weighted_sum=rainfall_sum)
    frame_mean = build_metric_frame(observed_at=observed_at, weighted_sum=rainfall_mean)

    axis_tops = _build_reference_axis_tops_for_run(
        frame_sum=frame_sum,
        frame_mean=frame_mean,
        base_date=base_date,
        graph_spans=("3d", "5d"),
        ref_graph_kinds=("sum", "mean"),
        left_top_default=60.0,
        right_top_default=300.0,
    )

    assert set(axis_tops) == {("3d", "sum"), ("3d", "mean"), ("5d", "sum"), ("5d", "mean")}


def test_draw_reference_chart_aligns_major_tick_count_between_axes() -> None:
    observed_at = [datetime(2024, 1, 1) + timedelta(hours=i) for i in range(120)]
    rainfall = [0.0] * 120
    rainfall[20] = 24.0
    rainfall[70] = 7.0
    frame = build_metric_frame(observed_at=observed_at, weighted_sum=rainfall)
    window = prepare_reference_window(frame)
    fig = draw_reference_chart(window=window, title="test", style=None, left_top=None, right_top=None, figure=None)
    ax1 = fig.axes[0]
    ax2 = fig.axes[2]
    left_top = float(ax1.get_ylim()[1])
    right_top = float(ax2.get_ylim()[1])
    left_ticks = [tick for tick in ax1.get_yticks() if 0.0 <= tick <= left_top]
    right_ticks = [tick for tick in ax2.get_yticks() if 0.0 <= tick <= right_top]
    assert len(left_ticks) == len(right_ticks)


def test_draw_reference_chart_keeps_manual_axis_tops() -> None:
    observed_at = [datetime(2024, 1, 1) + timedelta(hours=i) for i in range(120)]
    rainfall = [0.0] * 120
    rainfall[10] = 19.0
    rainfall[88] = 4.0
    frame = build_metric_frame(observed_at=observed_at, weighted_sum=rainfall)
    window = prepare_reference_window(frame)
    fig = draw_reference_chart(window=window, title="test", style=None, left_top=37.0, right_top=215.0, figure=None)
    ax1 = fig.axes[0]
    ax2 = fig.axes[2]
    assert float(ax1.get_ylim()[1]) == 37.0
    assert float(ax2.get_ylim()[1]) == 215.0


def test_draw_reference_chart_applies_x_axis_settings() -> None:
    observed_at = [datetime(2024, 1, 1) + timedelta(hours=i) for i in range(120)]
    rainfall = [0.0] * 120
    frame = build_metric_frame(observed_at=observed_at, weighted_sum=rainfall)
    window = prepare_reference_window(frame)
    style = GraphStyleProfile(
        x_tick_hours_list=[6, 12, 24],
        x_date_label_format="%m/%d",
        x_margin_hours_left=1.0,
        x_margin_hours_right=2.0,
    )
    fig = draw_reference_chart(window=window, title="test", style=style, left_top=None, right_top=None, figure=None)

    ax1 = fig.axes[0]
    ax_tbl = fig.axes[1]
    expected_xmin = mdates.date2num(window["observed_at"].min() - pd.Timedelta(hours=1.0))
    expected_xmax = mdates.date2num(window["observed_at"].max() + pd.Timedelta(hours=2.0))
    x0, x1 = ax1.get_xlim()
    assert x0 == pytest.approx(expected_xmin)
    assert x1 == pytest.approx(expected_xmax)

    hour_texts = [t.get_text() for t in ax_tbl.texts if t.get_position()[1] == style.table_row_top_y]
    assert "6" in hour_texts
    assert "12" in hour_texts
    assert "24" in hour_texts
    assert "18" not in hour_texts

    day_texts = [t.get_text() for t in ax_tbl.texts if t.get_position()[1] == style.table_row_bottom_y]
    assert any("/" in txt for txt in day_texts)


def test_draw_reference_chart_applies_day_boundary_offset_hours() -> None:
    observed_at = [datetime(2024, 1, 1) + timedelta(hours=i) for i in range(120)]
    rainfall = [0.0] * 120
    frame = build_metric_frame(observed_at=observed_at, weighted_sum=rainfall)
    window = prepare_reference_window(frame)
    style = GraphStyleProfile(day_boundary_offset_hours=0.5)
    fig = draw_reference_chart(window=window, title="test", style=style, left_top=None, right_top=None, figure=None)
    ax1 = fig.axes[0]

    boundary_lines = [line for line in ax1.lines if line.get_linestyle() == ":"]
    xs = [pd.Timestamp(line.get_xdata()[0]) for line in boundary_lines]
    expected = pd.Timestamp("2024-01-02 00:30:00")
    assert expected in xs
