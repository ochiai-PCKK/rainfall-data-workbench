from __future__ import annotations

import tkinter as tk
from dataclasses import asdict
from datetime import datetime, time, timedelta
from pathlib import Path
from tkinter import messagebox, ttk

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from .graph_renderer_reference import draw_reference_chart, prepare_reference_window
from .style_profile import (
    GraphStyleProfile,
    default_style_profile,
    default_style_profile_path,
    load_style_profile,
    save_style_profile,
)


def _profile_from_vars(vars_map: dict[str, tk.Variable]) -> GraphStyleProfile:
    base = asdict(default_style_profile())
    payload: dict[str, object] = {}
    for key, default in base.items():
        value = vars_map[key].get()
        if isinstance(default, bool):
            payload[key] = bool(value)
        elif isinstance(default, int):
            payload[key] = int(float(value))
        elif isinstance(default, float):
            payload[key] = float(value)
        else:
            payload[key] = value
    return GraphStyleProfile(**payload)


def _apply_profile_to_vars(profile: GraphStyleProfile, vars_map: dict[str, tk.Variable]) -> None:
    values = asdict(profile)
    for key, var in vars_map.items():
        var.set(values[key])


def _read_timeseries_csv(path: Path, value_kind: str) -> pd.DataFrame:
    src = pd.read_csv(path, encoding="utf-8-sig")
    required = {"observed_at_jst", "weighted_sum_mm", "weighted_mean_mm"}
    missing = sorted(required - set(src.columns))
    if missing:
        raise ValueError(f"CSV 必須列が不足しています: {missing}")
    col = "weighted_sum_mm" if value_kind == "sum" else "weighted_mean_mm"
    frame = pd.DataFrame({"observed_at": pd.to_datetime(src["observed_at_jst"]), "rainfall_mm": src[col]})
    return frame


def _build_synthetic_frame(value_kind: str) -> pd.DataFrame:
    start = datetime.combine(datetime.now().date() - timedelta(days=2), time(hour=0))
    observed_at = [start + timedelta(hours=i) for i in range(120)]
    # 体裁調整用の疑似波形（実データ依存なし）
    values: list[float] = []
    for i in range(120):
        x = i / 120.0
        peak1 = 45.0 * np.exp(-((x - 0.35) ** 2) / 0.0028)
        peak2 = 30.0 * np.exp(-((x - 0.72) ** 2) / 0.0048)
        base = 2.0 + 4.0 * np.sin(i / 8.5) ** 2
        v = max(0.0, base + peak1 + peak2)
        values.append(float(v))
    if value_kind == "mean":
        values = [v * 0.18 for v in values]
    return pd.DataFrame({"observed_at": observed_at, "rainfall_mm": values})


def _slice_preview_window(window_full: pd.DataFrame, span: str) -> pd.DataFrame:
    span_hours = 72 if span == "3d" else 120
    if len(window_full) < span_hours:
        raise ValueError(
            f"{span} プレビューに必要なデータが不足しています: required={span_hours} actual={len(window_full)}"
        )
    start_idx = max(0, (len(window_full) - span_hours) // 2)
    end_idx = start_idx + span_hours
    return window_full.iloc[start_idx:end_idx].copy()


def launch_style_tuner(
    *,
    input_csv: Path | None,
    value_kind: str,
    title: str,
    sample_mode: str,
    profile_path: Path | None,
    preview_span: str,
    master: tk.Misc | None = None,
) -> None:
    if input_csv is not None:
        frame = _read_timeseries_csv(input_csv, value_kind=value_kind)
    elif sample_mode == "synthetic":
        frame = _build_synthetic_frame(value_kind=value_kind)
    else:
        raise ValueError(f"未対応の sample_mode です: {sample_mode}")
    window_full = prepare_reference_window(frame)
    if preview_span not in ("3d", "5d"):
        raise ValueError(f"未対応の preview_span です: {preview_span}")
    available_spans: tuple[str, ...] = ("3d", "5d") if len(window_full) >= 120 else ("3d",)
    if preview_span not in available_spans:
        preview_span = available_spans[0]
    save_target = profile_path if profile_path else default_style_profile_path()
    profile = load_style_profile(save_target) if save_target.exists() else default_style_profile()

    owns_mainloop = master is None
    root: tk.Misc
    if owns_mainloop:
        root = tk.Tk()
    else:
        root = tk.Toplevel(master)
        root.transient(master)
    root.title("UC Rainfall グラフスタイル調整")
    root.geometry("1360x860")
    root.minsize(1180, 760)

    container = ttk.Frame(root, padding=8)
    container.pack(fill=tk.BOTH, expand=True)
    container.columnconfigure(0, weight=0)
    container.columnconfigure(1, weight=1)
    container.rowconfigure(0, weight=1)

    settings_panel = ttk.LabelFrame(container, text="設定", padding=6)
    settings_panel.grid(row=0, column=0, sticky="nsw", padx=(0, 8))
    settings_panel.rowconfigure(0, weight=1)
    settings_panel.columnconfigure(0, weight=1)

    settings_canvas = tk.Canvas(settings_panel, highlightthickness=0, width=470)
    settings_canvas.grid(row=0, column=0, sticky="nsew")
    settings_scroll = ttk.Scrollbar(settings_panel, orient=tk.VERTICAL, command=settings_canvas.yview)
    settings_scroll.grid(row=0, column=1, sticky="ns")
    settings_canvas.configure(yscrollcommand=settings_scroll.set)
    settings_inner = ttk.Frame(settings_canvas, padding=(2, 2))
    settings_window = settings_canvas.create_window((0, 0), window=settings_inner, anchor="nw")

    def _sync_settings_scroll(_event=None) -> None:
        settings_canvas.configure(scrollregion=settings_canvas.bbox("all"))
        settings_canvas.itemconfigure(settings_window, width=settings_canvas.winfo_width())

    settings_inner.bind("<Configure>", _sync_settings_scroll)
    settings_canvas.bind("<Configure>", _sync_settings_scroll)

    def _on_mousewheel(event) -> None:
        settings_canvas.yview_scroll(int(-event.delta / 120), "units")

    settings_canvas.bind("<Enter>", lambda _e: settings_canvas.bind_all("<MouseWheel>", _on_mousewheel))
    settings_canvas.bind("<Leave>", lambda _e: settings_canvas.unbind_all("<MouseWheel>"))

    preview_panel = ttk.LabelFrame(container, text="プレビュー", padding=8)
    preview_panel.grid(row=0, column=1, sticky="nsew")
    preview_panel.columnconfigure(0, weight=1)
    preview_panel.rowconfigure(0, weight=1)

    preview_holder = ttk.Frame(preview_panel, width=960, height=700)
    preview_holder.grid(row=0, column=0, sticky="nsew")
    preview_holder.pack_propagate(False)

    vars_map: dict[str, tk.Variable] = {
        "fig_width": tk.DoubleVar(value=profile.fig_width),
        "fig_height": tk.DoubleVar(value=profile.fig_height),
        "dpi": tk.IntVar(value=profile.dpi),
        "left": tk.DoubleVar(value=profile.left),
        "right": tk.DoubleVar(value=profile.right),
        "top": tk.DoubleVar(value=profile.top),
        "bottom": tk.DoubleVar(value=profile.bottom),
        "hspace": tk.DoubleVar(value=profile.hspace),
        "title_fontsize": tk.DoubleVar(value=profile.title_fontsize),
        "axis_label_fontsize": tk.DoubleVar(value=profile.axis_label_fontsize),
        "tick_fontsize": tk.DoubleVar(value=profile.tick_fontsize),
        "line_width": tk.DoubleVar(value=profile.line_width),
        "bar_width_hours": tk.DoubleVar(value=profile.bar_width_hours),
        "bar_edge_linewidth": tk.DoubleVar(value=profile.bar_edge_linewidth),
        "table_height_ratio": tk.DoubleVar(value=profile.table_height_ratio),
        "table_row_top_y": tk.DoubleVar(value=profile.table_row_top_y),
        "table_row_bottom_y": tk.DoubleVar(value=profile.table_row_bottom_y),
        "table_vertical_linewidth": tk.DoubleVar(value=profile.table_vertical_linewidth),
        "grid_y_visible": tk.BooleanVar(value=profile.grid_y_visible),
        "grid_y_linewidth": tk.DoubleVar(value=profile.grid_y_linewidth),
        "grid_y_color": tk.StringVar(value=profile.grid_y_color),
        "grid_y_alpha": tk.DoubleVar(value=profile.grid_y_alpha),
        "grid_x_visible": tk.BooleanVar(value=profile.grid_x_visible),
        "grid_x_linewidth": tk.DoubleVar(value=profile.grid_x_linewidth),
        "grid_x_color": tk.StringVar(value=profile.grid_x_color),
        "grid_x_alpha": tk.DoubleVar(value=profile.grid_x_alpha),
    }

    all_controls: list[tuple[str, str, float, float, float]] = [
        ("fig_width", "幅(inch)", 1.0, 18.0, 0.1),
        ("fig_height", "高さ(inch)", 1.0, 12.0, 0.1),
        ("dpi", "DPI", 72.0, 300.0, 1.0),
        ("left", "余白 left", 0.02, 0.3, 0.005),
        ("right", "余白 right", 0.7, 0.98, 0.005),
        ("top", "余白 top", 0.7, 0.98, 0.005),
        ("bottom", "余白 bottom", 0.02, 0.3, 0.005),
        ("hspace", "hspace", 0.0, 0.2, 0.005),
        ("title_fontsize", "タイトル", 8.0, 24.0, 0.5),
        ("axis_label_fontsize", "軸ラベル", 8.0, 20.0, 0.5),
        ("tick_fontsize", "目盛", 6.0, 18.0, 0.5),
        ("line_width", "折れ線幅", 0.5, 6.0, 0.1),
        ("bar_width_hours", "棒幅(時間)", 0.4, 1.2, 0.02),
        ("bar_edge_linewidth", "棒エッジ幅", 0.0, 2.0, 0.05),
        ("table_height_ratio", "テーブル高", 0.8, 4.0, 0.05),
        ("table_row_top_y", "テーブル上段Y", 1.0, 1.95, 0.02),
        ("table_row_bottom_y", "テーブル下段Y", 0.05, 0.95, 0.02),
        ("table_vertical_linewidth", "テーブル縦線", 0.2, 2.0, 0.05),
        ("grid_y_linewidth", "横グリッド線幅", 0.1, 2.0, 0.05),
        ("grid_y_alpha", "横グリッド透過", 0.1, 1.0, 0.05),
        ("grid_x_linewidth", "縦グリッド線幅", 0.1, 2.0, 0.05),
        ("grid_x_alpha", "縦グリッド透過", 0.1, 1.0, 0.05),
    ]

    pending_after_id: str | None = None
    current_canvas: FigureCanvasTkAgg | None = None
    current_widget: tk.Widget | None = None
    scale_widgets: dict[str, ttk.Scale] = {}
    is_internal_update = False
    is_redraw_in_progress = False
    last_holder_size = (0, 0)
    current_span_var = tk.StringVar(value=preview_span)

    def _holder_size_ready() -> bool:
        preview_holder.update_idletasks()
        return preview_holder.winfo_width() >= 320 and preview_holder.winfo_height() >= 240

    def _resolve_title_for_span(selected_span: str) -> str:
        selected_window = _slice_preview_window(window_full, selected_span)
        start_date = pd.to_datetime(selected_window["observed_at"]).min().strftime("%Y.%m.%d")
        end_date = pd.to_datetime(selected_window["observed_at"]).max().strftime("%Y.%m.%d")
        if title and ("{" in title and "}" in title):
            try:
                return title.format(start=start_date, end=end_date, span=selected_span)
            except Exception:  # noqa: BLE001
                return title
        if title:
            return title
        return f"流域平均雨量（{start_date} - {end_date}）"

    def _update_figure_slider_range(dpi_value: int) -> tuple[float, float]:
        preview_holder.update_idletasks()
        holder_w_raw = preview_holder.winfo_width()
        holder_h_raw = preview_holder.winfo_height()
        if holder_w_raw < 320 or holder_h_raw < 240:
            holder_w_raw = max(holder_w_raw, preview_holder.winfo_reqwidth())
            holder_h_raw = max(holder_h_raw, preview_holder.winfo_reqheight())
        holder_w = max(320, holder_w_raw - 16)
        holder_h = max(240, holder_h_raw - 16)
        safe_dpi = max(72, int(dpi_value))
        max_w = max(1.0, round(holder_w / safe_dpi, 1))
        max_h = max(1.0, round(holder_h / safe_dpi, 1))
        if "fig_width" in scale_widgets:
            scale_widgets["fig_width"].configure(to=max_w)
        if "fig_height" in scale_widgets:
            scale_widgets["fig_height"].configure(to=max_h)
        return max_w, max_h

    def _clamp_figure_size(profile_local: GraphStyleProfile) -> GraphStyleProfile:
        nonlocal is_internal_update
        if not _holder_size_ready():
            return profile_local
        max_w, max_h = _update_figure_slider_range(profile_local.dpi)
        clamped_w = min(max(profile_local.fig_width, 1.0), max_w)
        clamped_h = min(max(profile_local.fig_height, 1.0), max_h)
        if abs(clamped_w - profile_local.fig_width) > 1e-6 or abs(clamped_h - profile_local.fig_height) > 1e-6:
            is_internal_update = True
            try:
                if abs(clamped_w - profile_local.fig_width) > 1e-6:
                    vars_map["fig_width"].set(round(clamped_w, 1))
                if abs(clamped_h - profile_local.fig_height) > 1e-6:
                    vars_map["fig_height"].set(round(clamped_h, 1))
            finally:
                is_internal_update = False
        return GraphStyleProfile(**(asdict(profile_local) | {"fig_width": clamped_w, "fig_height": clamped_h}))

    def redraw() -> None:
        nonlocal pending_after_id, current_canvas, current_widget, is_redraw_in_progress
        if is_redraw_in_progress:
            return
        is_redraw_in_progress = True
        pending_after_id = None
        try:
            profile_local = _profile_from_vars(vars_map)
            profile_local = _clamp_figure_size(profile_local)
            selected_span = current_span_var.get()
            selected_window = _slice_preview_window(window_full, selected_span)
            current_title = _resolve_title_for_span(selected_span)

            fig = draw_reference_chart(window=selected_window, title=current_title, style=profile_local, figure=None)
            new_canvas = FigureCanvasTkAgg(fig, master=preview_holder)
            new_canvas.draw()
            new_widget = new_canvas.get_tk_widget()
            new_widget.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

            if current_widget is not None:
                old_fig = current_canvas.figure if current_canvas is not None else None
                current_widget.destroy()
                if old_fig is not None:
                    plt.close(old_fig)
            current_canvas = new_canvas
            current_widget = new_widget
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("描画エラー", str(exc))
        finally:
            is_redraw_in_progress = False

    def schedule_redraw(*_args) -> None:
        nonlocal pending_after_id
        if is_internal_update or is_redraw_in_progress:
            return
        if pending_after_id is not None:
            root.after_cancel(pending_after_id)
        pending_after_id = root.after(120, redraw)

    def on_holder_configure(_event: tk.Event) -> None:
        nonlocal last_holder_size
        current_size = (preview_holder.winfo_width(), preview_holder.winfo_height())
        if current_size == last_holder_size:
            return
        last_holder_size = current_size
        _update_figure_slider_range(vars_map["dpi"].get())
        schedule_redraw()

    def on_save_and_close() -> None:
        save_style_profile(save_target, _profile_from_vars(vars_map))
        messagebox.showinfo("保存完了", f"保存しました: {save_target}")
        root.destroy()

    def on_reset_default() -> None:
        _apply_profile_to_vars(default_style_profile(), vars_map)
        redraw()

    info_row = ttk.Frame(settings_inner)
    info_row.pack(fill=tk.X, pady=(0, 6))
    source_label = str(input_csv) if input_csv is not None else "テンプレート（疑似データ）"
    ttk.Label(info_row, text=f"対象データ: {source_label}", wraplength=440).pack(anchor=tk.W)
    ttk.Label(info_row, text=f"保存先: {save_target}", wraplength=440).pack(anchor=tk.W, pady=(2, 0))

    btn_row = ttk.Frame(settings_inner)
    btn_row.pack(fill=tk.X, pady=(0, 8))
    ttk.Button(btn_row, text="保存して閉じる", command=on_save_and_close).pack(side=tk.LEFT)
    ttk.Button(btn_row, text="既定値に戻す", command=on_reset_default).pack(side=tk.LEFT, padx=4)

    span_row = ttk.Frame(settings_inner)
    span_row.pack(fill=tk.X, pady=(0, 8))
    ttk.Label(span_row, text="表示期間", width=14).pack(side=tk.LEFT)
    span_combo = ttk.Combobox(
        span_row,
        width=8,
        state="readonly",
        values=available_spans,
        textvariable=current_span_var,
    )
    span_combo.pack(side=tk.LEFT)
    span_combo.bind("<<ComboboxSelected>>", schedule_redraw)

    grid_row = ttk.Frame(settings_inner)
    grid_row.pack(fill=tk.X)
    ttk.Checkbutton(
        grid_row,
        text="横グリッド表示",
        variable=vars_map["grid_y_visible"],
        command=schedule_redraw,
    ).pack(side=tk.LEFT)
    ttk.Checkbutton(
        grid_row,
        text="縦グリッド表示",
        variable=vars_map["grid_x_visible"],
        command=schedule_redraw,
    ).pack(side=tk.LEFT, padx=8)

    color_row_y = ttk.Frame(settings_inner)
    color_row_y.pack(fill=tk.X, pady=(0, 2))
    ttk.Label(color_row_y, text="横グリッド色", width=14).pack(side=tk.LEFT)
    ttk.Entry(color_row_y, width=12, textvariable=vars_map["grid_y_color"]).pack(side=tk.LEFT)
    vars_map["grid_y_color"].trace_add("write", schedule_redraw)

    color_row_x = ttk.Frame(settings_inner)
    color_row_x.pack(fill=tk.X, pady=(0, 6))
    ttk.Label(color_row_x, text="縦グリッド色", width=14).pack(side=tk.LEFT)
    ttk.Entry(color_row_x, width=12, textvariable=vars_map["grid_x_color"]).pack(side=tk.LEFT)
    vars_map["grid_x_color"].trace_add("write", schedule_redraw)

    for key, label, vmin, vmax, step in all_controls:
        frm = ttk.Frame(settings_inner)
        frm.pack(fill=tk.X, pady=1)
        ttk.Label(frm, text=label, width=14).pack(side=tk.LEFT)
        scale = ttk.Scale(
            frm,
            from_=vmin,
            to=vmax,
            variable=vars_map[key],
            orient=tk.HORIZONTAL,
        )
        scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        scale_widgets[key] = scale
        entry = ttk.Entry(frm, width=7, textvariable=vars_map[key])
        entry.pack(side=tk.LEFT, padx=(4, 0))
        vars_map[key].trace_add("write", schedule_redraw)

    _update_figure_slider_range(vars_map["dpi"].get())
    preview_holder.bind("<Configure>", on_holder_configure)
    root.after(80, redraw)
    if owns_mainloop:
        root.mainloop()
