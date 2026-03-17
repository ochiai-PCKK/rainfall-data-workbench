from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from .state import SERIES_MODE_LABELS, SPATIAL_METRIC_LABELS
from .widgets import add_labeled_combobox, add_labeled_entry, add_scrolled_log


def build_layout(app: Any) -> None:
    """全体レイアウトを構築する。"""
    app._register_widget("window.root", app.root, "window", "ルートウィンドウ")
    app.root.columnconfigure(0, weight=0, minsize=520)
    app.root.columnconfigure(1, weight=1)
    app.root.rowconfigure(0, weight=4)
    app.root.rowconfigure(1, weight=1)

    sidebar = ttk.Frame(app.root)
    sidebar.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(12, 8), pady=12)
    sidebar.columnconfigure(0, weight=1)
    sidebar.rowconfigure(0, weight=1)
    app._register_widget("frame.sidebar", sidebar, "frame", "左サイドバー")

    candidate_frame = ttk.Frame(app.root)
    candidate_frame.grid(row=0, column=1, sticky="nsew", padx=(8, 12), pady=(12, 6))
    candidate_frame.columnconfigure(0, weight=1)
    candidate_frame.rowconfigure(0, weight=1)

    log_frame = ttk.LabelFrame(app.root, text="処理ログ")
    log_frame.grid(row=1, column=1, sticky="nsew", padx=(8, 12), pady=(6, 12))
    log_frame.columnconfigure(0, weight=1)
    log_frame.rowconfigure(0, weight=1)

    build_input_area(app, sidebar)
    build_candidate_area(app, candidate_frame)
    build_log_area(app, log_frame)


def build_input_area(app: Any, frame: ttk.Frame) -> None:
    """入力エリアを組み立てる。"""
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)

    source_frame = ttk.LabelFrame(frame, text="データ入力")
    source_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 6))
    source_frame.columnconfigure(1, weight=1)
    source_frame.rowconfigure(1, weight=1)
    app._register_widget("frame.source", source_frame, "frame", "データ入力")

    params_frame = ttk.LabelFrame(frame, text="表示・解析条件")
    params_frame.grid(row=1, column=0, sticky="ew", pady=(0, 6))
    params_frame.columnconfigure(1, weight=1)
    app._register_widget("frame.params", params_frame, "frame", "表示・解析条件")

    actions_frame = ttk.LabelFrame(frame, text="主操作")
    actions_frame.grid(row=2, column=0, sticky="ew", pady=(0, 6))
    actions_frame.columnconfigure(0, weight=1)
    actions_frame.columnconfigure(1, weight=1)
    app._register_widget("frame.actions", actions_frame, "frame", "主操作")

    test_frame = ttk.LabelFrame(frame, text="テスト支援")
    test_frame.grid(row=3, column=0, sticky="ew")
    test_frame.columnconfigure(0, weight=1)
    test_frame.columnconfigure(1, weight=1)
    app._register_widget("frame.test", test_frame, "frame", "テスト支援")

    advanced_frame = ttk.LabelFrame(frame, text="詳細設定")
    advanced_frame.grid(row=4, column=0, sticky="ew", pady=(6, 0))
    advanced_frame.columnconfigure(1, weight=1)
    app._register_widget("frame.advanced", advanced_frame, "frame", "詳細設定")

    app.db_entry = add_labeled_entry(
        source_frame,
        row=0,
        label_text="データベース保存先",
        variable=app.state.db_path_var,
        entry_widget_id="entry.db_path",
        register_widget=app._register_widget,
        width=44,
    )
    browse_db_button = ttk.Button(source_frame, text="参照...", command=app._browse_db_path)
    browse_db_button.grid(row=0, column=2, sticky="w", padx=(0, 8), pady=4)
    app._register_widget("button.browse_db", browse_db_button, "button", "DB参照")
    app.db_entry.bind("<FocusOut>", lambda _event: app._on_db_path_changed())

    input_paths_label = ttk.Label(source_frame, text="取り込み対象")
    input_paths_label.grid(row=1, column=0, sticky="nw", padx=(0, 8), pady=4)
    app._register_widget("label.listbox.input_paths", input_paths_label, "label", "取り込み対象")

    input_list_frame = ttk.Frame(source_frame)
    input_list_frame.grid(row=1, column=1, sticky="nsew", padx=(0, 8), pady=4)
    input_list_frame.columnconfigure(0, weight=1)
    input_list_frame.rowconfigure(0, weight=1)
    app._register_widget("frame.input_path_list", input_list_frame, "frame", "取り込み対象一覧")
    app.input_paths_listbox = tk.Listbox(input_list_frame, height=10, exportselection=False)
    app.input_paths_listbox.grid(row=0, column=0, sticky="nsew")
    app._register_widget("listbox.input_paths", app.input_paths_listbox, "listbox", "取り込み対象一覧")
    input_scroll = ttk.Scrollbar(input_list_frame, orient="vertical", command=app.input_paths_listbox.yview)
    input_scroll.grid(row=0, column=1, sticky="ns")
    app.input_paths_listbox.configure(yscrollcommand=input_scroll.set)
    app.input_paths_listbox.bind("<<ListboxSelect>>", lambda _event: app._refresh_control_states())

    path_button_frame = ttk.Frame(source_frame)
    path_button_frame.grid(row=1, column=2, sticky="nw", padx=(0, 8), pady=4)
    app._register_widget("frame.input_path_buttons", path_button_frame, "frame", "取り込み対象ボタン群")
    add_zip_button = ttk.Button(path_button_frame, text="ZIP追加...", command=app._add_input_files)
    add_zip_button.grid(row=0, column=0, sticky="ew", pady=(0, 4))
    app._register_widget("button.add_zip", add_zip_button, "button", "ZIP追加")
    remove_selected_button = ttk.Button(
        path_button_frame,
        text="選択削除",
        command=app._remove_selected_input_paths,
    )
    remove_selected_button.grid(row=1, column=0, sticky="ew", pady=(0, 4))
    app._register_widget("button.remove_selected_path", remove_selected_button, "button", "選択削除")
    clear_paths_button = ttk.Button(path_button_frame, text="全削除", command=app._clear_input_paths)
    clear_paths_button.grid(row=2, column=0, sticky="ew")
    app._register_widget("button.clear_paths", clear_paths_button, "button", "全削除")

    app.polygon_dir_entry = add_labeled_entry(
        source_frame,
        row=2,
        label_text="流域ポリゴンフォルダ",
        variable=app.state.polygon_dir_var,
        entry_widget_id="entry.polygon_dir",
        register_widget=app._register_widget,
        width=44,
    )
    browse_polygon_button = ttk.Button(source_frame, text="参照...", command=app._browse_polygon_dir)
    browse_polygon_button.grid(row=2, column=2, sticky="w", padx=(0, 8), pady=4)
    app._register_widget("button.browse_polygon_dir", browse_polygon_button, "button", "ポリゴン参照")

    app.out_dir_entry = add_labeled_entry(
        source_frame,
        row=3,
        label_text="出力先フォルダ",
        variable=app.state.out_dir_var,
        entry_widget_id="entry.out_dir",
        register_widget=app._register_widget,
        width=44,
    )
    browse_out_dir_button = ttk.Button(source_frame, text="参照...", command=app._browse_out_dir)
    browse_out_dir_button.grid(row=3, column=2, sticky="w", padx=(0, 8), pady=4)
    app._register_widget("button.browse_out_dir", browse_out_dir_button, "button", "出力先参照")
    app.out_dir_entry.bind("<FocusOut>", lambda _event: app._validate_out_dir_inline())

    app.ingest_dataset_entry = add_labeled_entry(
        advanced_frame,
        row=0,
        label_text="取り込みID",
        variable=app.state.ingest_dataset_id_var,
        entry_widget_id="entry.ingest_dataset_id",
        register_widget=app._register_widget,
        width=24,
    )

    app.io_validation_label = ttk.Label(source_frame, text="", foreground="#b00020")
    app.io_validation_label.grid(row=5, column=1, columnspan=2, sticky="w", pady=(2, 0))
    app._register_widget("label.io_validation", app.io_validation_label, "label", "入出力検証")

    app.preferred_dataset_combo = add_labeled_combobox(
        advanced_frame,
        row=1,
        label_text="優先データセット",
        variable=app.state.preferred_dataset_id_var,
        values=[],
        widget_id="entry.preferred_dataset_id",
        register_widget=app._register_widget,
        width=24,
    )
    app.preferred_dataset_combo.bind("<<ComboboxSelected>>", lambda _event: app._on_preferred_dataset_changed())

    app.polygon_name_combo = add_labeled_combobox(
        params_frame,
        row=1,
        label_text="流域名",
        variable=app.state.polygon_name_var,
        values=[],
        widget_id="entry.polygon_name",
        register_widget=app._register_widget,
        width=24,
    )
    app.polygon_name_combo.bind("<<ComboboxSelected>>", lambda _event: app._on_polygon_name_changed())

    app.series_mode_combo = add_labeled_combobox(
        params_frame,
        row=2,
        label_text="グラフ系列",
        variable=app.state.series_mode_var,
        values=list(SERIES_MODE_LABELS.values()),
        widget_id="combobox.series_mode",
        register_widget=app._register_widget,
        width=24,
    )
    app.series_mode_combo.bind("<<ComboboxSelected>>", lambda _event: app._refresh_control_states())

    app.local_row_combo = add_labeled_combobox(
        params_frame,
        row=3,
        label_text="流域内行",
        variable=app.state.local_row_var,
        values=[],
        widget_id="entry.local_row",
        register_widget=app._register_widget,
        width=24,
    )
    app.local_col_combo = add_labeled_combobox(
        params_frame,
        row=4,
        label_text="流域内列",
        variable=app.state.local_col_var,
        values=[],
        widget_id="entry.local_col",
        register_widget=app._register_widget,
        width=24,
    )

    build_timestamp_selector(
        app,
        params_frame,
        row=5,
        label_text="グラフ開始日時",
        prefix="view_start",
        year_var=app.state.view_start_year_var,
        month_var=app.state.view_start_month_var,
        day_var=app.state.view_start_day_var,
        time_var=app.state.view_start_time_var,
        on_change=app._on_view_start_changed,
    )
    build_timestamp_selector(
        app,
        params_frame,
        row=6,
        label_text="グラフ終了日時",
        prefix="view_end",
        year_var=app.state.view_end_year_var,
        month_var=app.state.view_end_month_var,
        day_var=app.state.view_end_day_var,
        time_var=app.state.view_end_time_var,
        on_change=app._on_view_end_changed,
    )

    app.params_validation_label = ttk.Label(params_frame, text="", foreground="#b00020")
    app.params_validation_label.grid(row=7, column=0, columnspan=2, sticky="w", pady=(2, 0))
    app._register_widget("label.params_validation", app.params_validation_label, "label", "解析条件検証")

    app.test_mode_check = ttk.Checkbutton(
        test_frame,
        text="テストモード",
        variable=app.state.test_mode_var,
        command=app._on_test_mode_toggled,
    )
    app.test_mode_check.grid(row=0, column=0, sticky="w", pady=(0, 6))
    app._register_widget("check.test_mode", app.test_mode_check, "checkbutton", "テストモード")

    app.status_label = ttk.Label(test_frame, textvariable=app.state.status_var)
    app.status_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 6))
    app._register_widget("label.status", app.status_label, "label", "状態表示")

    main_button_frame = ttk.Frame(actions_frame)
    main_button_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 6))
    app._register_widget("frame.main_buttons", main_button_frame, "frame", "主要ボタン群")
    tool_button_frame = ttk.Frame(test_frame)
    tool_button_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 0))
    app._register_widget("frame.tool_buttons", tool_button_frame, "frame", "テスト支援ボタン群")

    app._main_buttons = []
    primary_button_defs = [
        ("button.init_db", "DB初期化", app._handle_init_db),
        ("button.ingest", "DBへ登録", app._handle_ingest),
        ("button.plot", "グラフ出力", app._handle_plot),
    ]
    utility_button_defs = [
        ("button.save_test_context", "状態保存", app._handle_save_test_context),
        ("button.save_widget_tree", "ウィジェット保存", app._handle_save_widget_tree),
        ("button.save_screenshot", "画面を保存", app._handle_save_screenshot),
        ("button.save_log", "ログを保存", app._handle_save_log),
    ]
    for index, (widget_id, label, command) in enumerate(primary_button_defs):
        button = ttk.Button(main_button_frame, text=label, command=command)
        button.grid(row=0, column=index, sticky="ew", padx=(0, 8), pady=(0, 4))
        main_button_frame.columnconfigure(index, weight=1)
        app._register_widget(widget_id, button, "button", label)
        app._main_buttons.append(button)
    for index, (widget_id, label, command) in enumerate(utility_button_defs):
        button = ttk.Button(tool_button_frame, text=label, command=command)
        button.grid(row=index // 2, column=index % 2, sticky="ew", padx=(0, 8), pady=(0, 4))
        tool_button_frame.columnconfigure(index % 2, weight=1)
        app._register_widget(widget_id, button, "button", label)
        app._main_buttons.append(button)


def build_candidate_area(app: Any, frame: ttk.Frame) -> None:
    """候補セルテーブルと面ビューを構築する。"""
    app.view_notebook = ttk.Notebook(frame)
    app.view_notebook.grid(row=0, column=0, sticky="nsew")
    app._register_widget("notebook.views", app.view_notebook, "notebook", "候補・面ビュー")

    table_tab = ttk.Frame(app.view_notebook)
    table_tab.columnconfigure(0, weight=1)
    table_tab.rowconfigure(1, weight=1)
    app._register_widget("tab.candidate_table", table_tab, "tab", "候補セル表")

    spatial_tab = ttk.Frame(app.view_notebook)
    spatial_tab.columnconfigure(0, weight=1)
    spatial_tab.rowconfigure(1, weight=1)
    app._register_widget("tab.spatial_view", spatial_tab, "tab", "面ビュー")

    app.view_notebook.add(table_tab, text="候補セル表")
    app.view_notebook.add(spatial_tab, text="面ビュー")

    table_toolbar = ttk.Frame(table_tab)
    table_toolbar.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 2))
    table_toolbar.columnconfigure(1, weight=1)
    app._register_widget("frame.candidate_toolbar", table_toolbar, "frame", "候補セル表操作")
    candidate_refresh_button = ttk.Button(table_toolbar, text="候補更新", command=app._handle_list_candidates)
    candidate_refresh_button.grid(row=0, column=0, sticky="w")
    app._register_widget("button.list_candidates", candidate_refresh_button, "button", "候補更新")
    app._main_buttons.append(candidate_refresh_button)
    app.candidate_summary_label = ttk.Label(table_toolbar, text="候補セル 未取得")
    app.candidate_summary_label.grid(row=0, column=1, sticky="w", padx=(10, 0))
    app._register_widget("label.candidate_summary", app.candidate_summary_label, "label", "候補セル概要")

    columns = ("流域名", "流域内行", "流域内列", "中心X", "中心Y", "重なり率", "データセット数")
    app.candidate_tree = ttk.Treeview(table_tab, columns=columns, show="headings", height=14)
    app.candidate_tree.grid(row=1, column=0, sticky="nsew")
    app._register_widget("tree.candidates", app.candidate_tree, "treeview", "候補セル一覧")
    for name in columns:
        app.candidate_tree.heading(name, text=name)
        width = 110 if name == "流域名" else 90
        if name in {"中心X", "中心Y"}:
            width = 130
        app.candidate_tree.column(name, width=width, stretch=True, anchor="center")
    scrollbar = ttk.Scrollbar(table_tab, orient="vertical", command=app.candidate_tree.yview)
    scrollbar.grid(row=1, column=1, sticky="ns")
    app.candidate_tree.configure(yscrollcommand=scrollbar.set)
    app.candidate_tree.bind("<<TreeviewSelect>>", app._on_candidate_selected)

    build_spatial_area(app, spatial_tab)


def build_spatial_area(app: Any, frame: ttk.Frame) -> None:
    """面ビュータブを構築する。"""
    control_frame = ttk.Frame(frame)
    control_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 2))
    control_frame.columnconfigure(1, weight=1)
    control_frame.columnconfigure(3, weight=1)
    app._register_widget("frame.spatial_controls", control_frame, "frame", "面ビュー操作")

    build_timestamp_selector(
        app,
        control_frame,
        row=0,
        label_text="面ビュー時刻",
        prefix="spatial",
        year_var=app.state.spatial_year_var,
        month_var=app.state.spatial_month_var,
        day_var=app.state.spatial_day_var,
        time_var=app.state.spatial_time_var,
        on_change=app._on_spatial_timestamp_changed,
    )
    app.spatial_metric_combo = add_labeled_combobox(
        control_frame,
        row=1,
        label_text="面ビュー指標",
        variable=app.state.spatial_metric_var,
        values=list(SPATIAL_METRIC_LABELS.values()),
        widget_id="combobox.spatial_metric",
        register_widget=app._register_widget,
        width=22,
    )
    render_button = ttk.Button(control_frame, text="面を描画", command=app._handle_render_spatial_view)
    render_button.grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
    app._register_widget("button.render_spatial_view", render_button, "button", "面を描画")
    app._main_buttons.append(render_button)
    clear_button = ttk.Button(control_frame, text="選択解除", command=app._clear_spatial_selection)
    clear_button.grid(row=2, column=1, sticky="w", padx=(0, 8), pady=(6, 0))
    app._register_widget("button.clear_spatial_selection", clear_button, "button", "選択解除")
    app._main_buttons.append(clear_button)
    app.spatial_status_label = ttk.Label(control_frame, text="")
    app.spatial_status_label.grid(row=2, column=2, columnspan=2, sticky="w", pady=(6, 0))
    app._register_widget("label.spatial_status", app.spatial_status_label, "label", "面ビュー状態")

    canvas_frame = ttk.Frame(frame)
    canvas_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 6))
    canvas_frame.columnconfigure(0, weight=1)
    canvas_frame.rowconfigure(0, weight=1)
    app._register_widget("frame.spatial_canvas", canvas_frame, "frame", "面ビュー描画枠")

    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure

    app.spatial_figure = Figure(figsize=(8.0, 5.4), dpi=100)
    app.spatial_ax = app.spatial_figure.add_subplot(111)
    app.spatial_canvas = FigureCanvasTkAgg(app.spatial_figure, master=canvas_frame)
    app.spatial_canvas.draw()
    app.spatial_canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
    app._register_widget("canvas.spatial_view", app.spatial_canvas.get_tk_widget(), "canvas", "面ビュー")
    app.spatial_canvas.mpl_connect("button_press_event", app._on_spatial_canvas_click)


def build_log_area(app: Any, frame: ttk.LabelFrame) -> None:
    """ログエリアを構築する。"""
    app.log_text = add_scrolled_log(frame, widget_id="text.log", register_widget=app._register_widget, height=10)
    app.log_text.configure(state="disabled")


def build_timestamp_selector(
    app: Any,
    parent: tk.Misc,
    *,
    row: int,
    label_text: str,
    prefix: str,
    year_var: tk.StringVar,
    month_var: tk.StringVar,
    day_var: tk.StringVar,
    time_var: tk.StringVar,
    on_change,
) -> None:
    """年 / 月 / 日 / 時刻の4段選択を構築する。"""
    label = ttk.Label(parent, text=label_text)
    label.grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
    app._register_widget(f"label.{prefix}_timestamp", label, "label", label_text)

    holder = ttk.Frame(parent)
    holder.grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=2)
    holder.columnconfigure(0, weight=1)
    holder.columnconfigure(1, weight=1)
    holder.columnconfigure(2, weight=1)
    holder.columnconfigure(3, weight=1)
    app._register_widget(f"frame.{prefix}_timestamp", holder, "frame", f"{label_text}選択")

    year_combo = ttk.Combobox(holder, textvariable=year_var, values=[], width=8, state="readonly")
    year_combo.grid(row=0, column=0, sticky="ew", padx=(0, 4))
    app._register_widget(f"combobox.{prefix}_year", year_combo, "combobox", f"{label_text}年")
    year_combo.bind("<<ComboboxSelected>>", lambda _event: on_change("year"))

    month_combo = ttk.Combobox(holder, textvariable=month_var, values=[], width=6, state="readonly")
    month_combo.grid(row=0, column=1, sticky="ew", padx=(0, 4))
    app._register_widget(f"combobox.{prefix}_month", month_combo, "combobox", f"{label_text}月")
    month_combo.bind("<<ComboboxSelected>>", lambda _event: on_change("month"))

    day_combo = ttk.Combobox(holder, textvariable=day_var, values=[], width=6, state="readonly")
    day_combo.grid(row=0, column=2, sticky="ew", padx=(0, 4))
    app._register_widget(f"combobox.{prefix}_day", day_combo, "combobox", f"{label_text}日")
    day_combo.bind("<<ComboboxSelected>>", lambda _event: on_change("day"))

    time_combo = ttk.Combobox(holder, textvariable=time_var, values=[], width=8, state="readonly")
    time_combo.grid(row=0, column=3, sticky="ew")
    app._register_widget(f"combobox.{prefix}_time", time_combo, "combobox", f"{label_text}時刻")
    time_combo.bind("<<ComboboxSelected>>", lambda _event: on_change("time"))

    setattr(app, f"{prefix}_year_combo", year_combo)
    setattr(app, f"{prefix}_month_combo", month_combo)
    setattr(app, f"{prefix}_day_combo", day_combo)
    setattr(app, f"{prefix}_time_combo", time_combo)
