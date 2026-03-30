from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Any, cast


def collect_state_payload(app: Any) -> dict[str, object]:
    return {
        "run_mode": app.run_mode_var.get().strip(),
        "input_zipdir": app.input_zipdir_var.get().strip(),
        "input_excel": app.input_excel_var.get().strip(),
        "excel_graph_span": app.excel_panel.get_span(),
        "excel_selected_event_keys": app.excel_panel.get_selected_event_keys(),
        "rain_period_input_mode": app.rain_panel.period_input_mode_var.get().strip(),
        "rain_window_mode": app.rain_panel.get_window_mode(),
        "rain_selected_dates": [app.rain_panel.date_listbox.get(i) for i in app.rain_panel.date_listbox.curselection()],
        "rain_dates_csv_path": app.rain_dates_csv_var.get().strip(),
        "rain_dates_excel_path": app.rain_dates_excel_var.get().strip(),
        "rain_compute_engine": app.compute_engine_var.get().strip(),
        "output_dir": app.output_dir_var.get().strip(),
        "polygon_dir": app.polygon_dir_var.get().strip(),
        "period_start": app.start_date_var.get().strip(),
        "period_end": app.end_date_var.get().strip(),
        "selected_regions": [k for k, v in app.region_vars.items() if v.get()],
        "selected_outputs": [k for k, v in app.output_vars.items() if v.get()],
        "ref_graph_kinds": [k for k, v in app.graph_kind_vars.items() if v.get()],
        "enable_log": bool(app.enable_log_var.get()),
        "export_svg": bool(app.export_svg_var.get()),
        "merge_a4_enabled": bool(app.merge_a4_enabled_var.get()),
        "merge_a4_columns": app.merge_a4_columns_var.get().strip(),
        "merge_a4_rows": app.merge_a4_rows_var.get().strip(),
    }


def apply_loaded_state(app: Any, state: dict[str, object], *, run_modes: tuple[str, ...], runtime_engines: tuple[str, ...]) -> None:
    mode = str(state.get("run_mode", app.run_mode_var.get()))
    app.run_mode_var.set(mode if mode in run_modes else run_modes[0])
    app.input_zipdir_var.set(str(state.get("input_zipdir", app.input_zipdir_var.get())))
    app.input_excel_var.set(str(state.get("input_excel", app.input_excel_var.get())))
    app.rain_panel.period_input_mode_var.set(str(state.get("rain_period_input_mode", app.rain_panel.period_input_mode_var.get())))
    app.rain_panel.window_mode_var.set(str(state.get("rain_window_mode", app.rain_panel.get_window_mode())))
    app.rain_dates_csv_var.set(str(state.get("rain_dates_csv_path", app.rain_dates_csv_var.get())))
    app.rain_dates_excel_var.set(str(state.get("rain_dates_excel_path", app.rain_dates_excel_var.get())))
    loaded_engine = str(state.get("rain_compute_engine", app.compute_engine_var.get())).strip()
    app.compute_engine_var.set(loaded_engine if loaded_engine in runtime_engines else "python")
    app.rain_panel.mark_zipdir_changed()
    app.rain_panel.refresh_candidates(app.input_zipdir_var.get().strip(), force=False)
    selected_rain_dates = set(cast(list[str], state.get("rain_selected_dates", [])))
    if selected_rain_dates and app.rain_panel.date_listbox.size() > 0:
        app.rain_panel.date_listbox.selection_clear(0, tk.END)
        for i in range(app.rain_panel.date_listbox.size()):
            val = app.rain_panel.date_listbox.get(i)
            if val in selected_rain_dates:
                app.rain_panel.date_listbox.selection_set(i)
        app.rain_panel._update_selected_count()
    app.excel_panel.refresh_candidates(app.input_excel_var.get().strip())
    app.excel_panel.span_var.set(str(state.get("excel_graph_span", app.excel_panel.get_span())))
    selected_excel = set(cast(list[str], state.get("excel_selected_event_keys", state.get("excel_selected_sheets", []))))
    app.excel_panel.select_by_event_keys(selected_excel)
    app.output_dir_var.set(str(state.get("output_dir", app.output_dir_var.get())))
    app.polygon_dir_var.set(str(state.get("polygon_dir", app.polygon_dir_var.get())))
    app.start_date_var.set(str(state.get("period_start", app.start_date_var.get())))
    app.end_date_var.set(str(state.get("period_end", app.end_date_var.get())))
    app.enable_log_var.set(bool(state.get("enable_log", app.enable_log_var.get())))
    app.export_svg_var.set(bool(state.get("export_svg", app.export_svg_var.get())))
    app.merge_a4_enabled_var.set(bool(state.get("merge_a4_enabled", app.merge_a4_enabled_var.get())))
    app.merge_a4_columns_var.set(str(state.get("merge_a4_columns", app.merge_a4_columns_var.get())))
    app.merge_a4_rows_var.set(str(state.get("merge_a4_rows", app.merge_a4_rows_var.get())))

    selected_regions = set(cast(list[str], state.get("selected_regions", [])))
    if selected_regions:
        for key, var in app.region_vars.items():
            var.set(key in selected_regions)
    selected_outputs = set(cast(list[str], state.get("selected_outputs", [])))
    if selected_outputs:
        for key, var in app.output_vars.items():
            var.set(key in selected_outputs)
    graph_kinds = set(cast(list[str], state.get("ref_graph_kinds", [])))
    if graph_kinds:
        for key, var in app.graph_kind_vars.items():
            var.set(key in graph_kinds)
    app._saved_rain_region_state = {k: bool(v.get()) for k, v in app.region_vars.items()}
    app._saved_rain_output_state = {k: bool(v.get()) for k, v in app.output_vars.items()}
    app._update_input_mode_visibility()
