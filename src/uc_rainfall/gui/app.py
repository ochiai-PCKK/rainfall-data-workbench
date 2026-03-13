from __future__ import annotations

import argparse
from datetime import datetime
import logging
from pathlib import Path
from queue import Empty, Queue
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib import cm
from matplotlib.colors import Normalize
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
import pandas as pd

from ..db import initialize_schema, open_db
from ..services import (
    build_spatial_view_payload,
    generate_metric_event_charts,
    ingest_uc_rainfall,
    ingest_uc_rainfall_many,
    list_candidate_cells,
)
from ..settings_store import update_settings
from .context_store import (
    clear_action_request,
    get_last_screenshot_path,
    load_action_request,
    save_action_result,
    save_gui_context,
    save_gui_log,
    save_last_run,
    save_widget_tree,
)
from .logging_handler import GuiLogHandler
from .state import GuiState, SERIES_MODE_LABELS, SPATIAL_METRIC_LABELS
from .widgets import add_labeled_combobox, add_labeled_entry, add_scrolled_log


LOGGER = logging.getLogger(__name__)
ALL_DATASETS_LABEL = "全データセット"


def _parse_datetime(value: str) -> datetime:
    """`YYYY-MM-DDTHH:MM:SS` 形式の文字列を解釈する。"""
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")


def _display_input_path(path: str) -> str:
    """入力一覧に表示する短い名称を返す。"""
    return Path(path).name


def _compose_timestamp(year_value: str, month_value: str, day_value: str, time_value: str) -> str:
    """年 / 月 / 日 / 時刻から ISO 文字列を組み立てる。"""
    if not year_value or not month_value or not day_value or not time_value:
        return ""
    return f"{year_value}-{month_value}-{day_value}T{time_value}:00"


class UcRainfallGuiApp:
    """UC 降雨処理の Tkinter GUI 本体。"""

    def __init__(self, *, test_mode: bool = False) -> None:
        self.root = tk.Tk()
        self.root.title("UC降雨処理 GUI")
        self.root.geometry("1480x980")
        self.root.minsize(1240, 820)
        self.state = GuiState(self.root, test_mode_default=test_mode)
        self._log_handler: GuiLogHandler | None = None
        self._candidate_items: dict[str, dict[str, Any]] = {}
        self._ui_queue: Queue[tuple[str, Any]] = Queue()
        self._busy_action: str | None = None
        self._active_dialog: tk.Toplevel | None = None
        self._spatial_payload: dict[str, Any] | None = None
        self._spatial_cell_lookup: dict[tuple[int, int], dict[str, Any]] = {}
        self._spatial_rectangles: list[tuple[Rectangle, dict[str, Any]]] = []
        self._spatial_colorbar = None
        self._db_metadata_cache: dict[str, tuple[list[str], list[str]]] = {}
        self._time_candidates_cache: dict[tuple[str, str, str | None], list[pd.Timestamp]] = {}
        self._candidate_frame_cache: dict[tuple[str, str, str | None], pd.DataFrame] = {}
        self._build_layout()
        if test_mode:
            self.root.attributes("-topmost", True)
        self._configure_logging()
        self._apply_cached_input_paths()
        self._load_db_metadata()
        self._refresh_control_states()
        self._update_test_summary()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(120, self._process_ui_queue)
        self.root.after(350, self._poll_action_requests)

    def run(self) -> None:
        """GUI を起動する。"""
        self.root.mainloop()

    def _configure_logging(self) -> None:
        """GUI 用 logging 設定を行う。"""
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        self._log_handler = GuiLogHandler(self._enqueue_log_line)
        root_logger.addHandler(self._log_handler)

    def _build_layout(self) -> None:
        """全体レイアウトを構築する。"""
        self._register_widget("window.root", self.root, "window", "ルートウィンドウ")
        self.root.columnconfigure(0, weight=0, minsize=520)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=4)
        self.root.rowconfigure(1, weight=1)

        sidebar = ttk.Frame(self.root)
        sidebar.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(12, 8), pady=12)
        sidebar.columnconfigure(0, weight=1)
        sidebar.rowconfigure(0, weight=1)
        self._register_widget("frame.sidebar", sidebar, "frame", "左サイドバー")

        candidate_frame = ttk.Frame(self.root)
        candidate_frame.grid(row=0, column=1, sticky="nsew", padx=(8, 12), pady=(12, 6))
        candidate_frame.columnconfigure(0, weight=1)
        candidate_frame.rowconfigure(0, weight=1)

        log_frame = ttk.LabelFrame(self.root, text="処理ログ")
        log_frame.grid(row=1, column=1, sticky="nsew", padx=(8, 12), pady=(6, 12))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self._build_input_area(sidebar)
        self._build_candidate_area(candidate_frame)
        self._build_log_area(log_frame)

    def _build_input_area(self, frame: ttk.Frame) -> None:
        """入力エリアを組み立てる。"""
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        source_frame = ttk.LabelFrame(frame, text="データ入力")
        source_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 6))
        source_frame.columnconfigure(1, weight=1)
        source_frame.rowconfigure(1, weight=1)
        self._register_widget("frame.source", source_frame, "frame", "データ入力")

        params_frame = ttk.LabelFrame(frame, text="表示・解析条件")
        params_frame.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        params_frame.columnconfigure(1, weight=1)
        self._register_widget("frame.params", params_frame, "frame", "表示・解析条件")

        actions_frame = ttk.LabelFrame(frame, text="主操作")
        actions_frame.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        actions_frame.columnconfigure(0, weight=1)
        actions_frame.columnconfigure(1, weight=1)
        self._register_widget("frame.actions", actions_frame, "frame", "主操作")

        test_frame = ttk.LabelFrame(frame, text="テスト支援")
        test_frame.grid(row=3, column=0, sticky="ew")
        test_frame.columnconfigure(0, weight=1)
        test_frame.columnconfigure(1, weight=1)
        self._register_widget("frame.test", test_frame, "frame", "テスト支援")

        advanced_frame = ttk.LabelFrame(frame, text="詳細設定")
        advanced_frame.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        advanced_frame.columnconfigure(1, weight=1)
        self._register_widget("frame.advanced", advanced_frame, "frame", "詳細設定")

        self.db_entry = add_labeled_entry(
            source_frame,
            row=0,
            label_text="データベース保存先",
            variable=self.state.db_path_var,
            entry_widget_id="entry.db_path",
            register_widget=self._register_widget,
            width=44,
        )
        browse_db_button = ttk.Button(source_frame, text="参照...", command=self._browse_db_path)
        browse_db_button.grid(row=0, column=2, sticky="w", padx=(0, 8), pady=4)
        self._register_widget("button.browse_db", browse_db_button, "button", "DB参照")
        self.db_entry.bind("<FocusOut>", lambda _event: self._on_db_path_changed())

        input_paths_label = ttk.Label(source_frame, text="取り込み対象")
        input_paths_label.grid(row=1, column=0, sticky="nw", padx=(0, 8), pady=4)
        self._register_widget("label.listbox.input_paths", input_paths_label, "label", "取り込み対象")

        input_list_frame = ttk.Frame(source_frame)
        input_list_frame.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=4)
        input_list_frame.columnconfigure(0, weight=1)
        input_list_frame.rowconfigure(0, weight=1)
        self._register_widget("frame.input_path_list", input_list_frame, "frame", "取り込み対象一覧")
        self.input_paths_listbox = tk.Listbox(input_list_frame, height=10, exportselection=False)
        self.input_paths_listbox.grid(row=0, column=0, sticky="nsew")
        self._register_widget("listbox.input_paths", self.input_paths_listbox, "listbox", "取り込み対象一覧")
        input_scroll = ttk.Scrollbar(input_list_frame, orient="vertical", command=self.input_paths_listbox.yview)
        input_scroll.grid(row=0, column=1, sticky="ns")
        self.input_paths_listbox.configure(yscrollcommand=input_scroll.set)
        self.input_paths_listbox.bind("<<ListboxSelect>>", lambda _event: self._refresh_control_states())

        path_button_frame = ttk.Frame(source_frame)
        path_button_frame.grid(row=1, column=2, sticky="nw", padx=(0, 8), pady=4)
        self._register_widget("frame.input_path_buttons", path_button_frame, "frame", "取り込み対象ボタン群")
        add_zip_button = ttk.Button(path_button_frame, text="ZIP追加...", command=self._add_input_files)
        add_zip_button.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self._register_widget("button.add_zip", add_zip_button, "button", "ZIP追加")
        remove_selected_button = ttk.Button(path_button_frame, text="選択削除", command=self._remove_selected_input_paths)
        remove_selected_button.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        self._register_widget("button.remove_selected_path", remove_selected_button, "button", "選択削除")
        clear_paths_button = ttk.Button(path_button_frame, text="全削除", command=self._clear_input_paths)
        clear_paths_button.grid(row=2, column=0, sticky="ew")
        self._register_widget("button.clear_paths", clear_paths_button, "button", "全削除")

        self.polygon_dir_entry = add_labeled_entry(
            source_frame,
            row=2,
            label_text="流域ポリゴンフォルダ",
            variable=self.state.polygon_dir_var,
            entry_widget_id="entry.polygon_dir",
            register_widget=self._register_widget,
            width=44,
        )
        browse_polygon_button = ttk.Button(source_frame, text="参照...", command=self._browse_polygon_dir)
        browse_polygon_button.grid(row=2, column=2, sticky="w", padx=(0, 8), pady=4)
        self._register_widget("button.browse_polygon_dir", browse_polygon_button, "button", "ポリゴン参照")

        self.out_dir_entry = add_labeled_entry(
            source_frame,
            row=3,
            label_text="出力先フォルダ",
            variable=self.state.out_dir_var,
            entry_widget_id="entry.out_dir",
            register_widget=self._register_widget,
            width=44,
        )
        browse_out_dir_button = ttk.Button(source_frame, text="参照...", command=self._browse_out_dir)
        browse_out_dir_button.grid(row=3, column=2, sticky="w", padx=(0, 8), pady=4)
        self._register_widget("button.browse_out_dir", browse_out_dir_button, "button", "出力先参照")
        self.out_dir_entry.bind("<FocusOut>", lambda _event: self._validate_out_dir_inline())

        self.ingest_dataset_entry = add_labeled_entry(
            advanced_frame,
            row=0,
            label_text="取り込みID",
            variable=self.state.ingest_dataset_id_var,
            entry_widget_id="entry.ingest_dataset_id",
            register_widget=self._register_widget,
            width=24,
        )

        self.io_validation_label = ttk.Label(source_frame, text="", foreground="#b00020")
        self.io_validation_label.grid(row=5, column=1, columnspan=2, sticky="w", pady=(2, 0))
        self._register_widget("label.io_validation", self.io_validation_label, "label", "入出力検証")

        self.preferred_dataset_combo = add_labeled_combobox(
            advanced_frame,
            row=1,
            label_text="優先データセット",
            variable=self.state.preferred_dataset_id_var,
            values=[],
            widget_id="entry.preferred_dataset_id",
            register_widget=self._register_widget,
            width=24,
        )
        self.preferred_dataset_combo.bind("<<ComboboxSelected>>", lambda _event: self._on_preferred_dataset_changed())

        self.polygon_name_combo = add_labeled_combobox(
            params_frame,
            row=1,
            label_text="流域名",
            variable=self.state.polygon_name_var,
            values=[],
            widget_id="entry.polygon_name",
            register_widget=self._register_widget,
            width=24,
        )
        self.polygon_name_combo.bind("<<ComboboxSelected>>", lambda _event: self._on_polygon_name_changed())

        self.series_mode_combo = add_labeled_combobox(
            params_frame,
            row=2,
            label_text="グラフ系列",
            variable=self.state.series_mode_var,
            values=list(SERIES_MODE_LABELS.values()),
            widget_id="combobox.series_mode",
            register_widget=self._register_widget,
            width=24,
        )
        self.series_mode_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_control_states())

        self.local_row_combo = add_labeled_combobox(
            params_frame,
            row=3,
            label_text="流域内行",
            variable=self.state.local_row_var,
            values=[],
            widget_id="entry.local_row",
            register_widget=self._register_widget,
            width=24,
        )
        self.local_col_combo = add_labeled_combobox(
            params_frame,
            row=4,
            label_text="流域内列",
            variable=self.state.local_col_var,
            values=[],
            widget_id="entry.local_col",
            register_widget=self._register_widget,
            width=24,
        )

        self._build_timestamp_selector(
            params_frame,
            row=5,
            label_text="グラフ開始日時",
            prefix="view_start",
            year_var=self.state.view_start_year_var,
            month_var=self.state.view_start_month_var,
            day_var=self.state.view_start_day_var,
            time_var=self.state.view_start_time_var,
            on_change=self._on_view_start_changed,
        )
        self._build_timestamp_selector(
            params_frame,
            row=6,
            label_text="グラフ終了日時",
            prefix="view_end",
            year_var=self.state.view_end_year_var,
            month_var=self.state.view_end_month_var,
            day_var=self.state.view_end_day_var,
            time_var=self.state.view_end_time_var,
            on_change=self._on_view_end_changed,
        )

        self.params_validation_label = ttk.Label(params_frame, text="", foreground="#b00020")
        self.params_validation_label.grid(row=7, column=0, columnspan=2, sticky="w", pady=(2, 0))
        self._register_widget("label.params_validation", self.params_validation_label, "label", "解析条件検証")

        self.test_mode_check = ttk.Checkbutton(
            test_frame,
            text="テストモード",
            variable=self.state.test_mode_var,
            command=self._on_test_mode_toggled,
        )
        self.test_mode_check.grid(row=0, column=0, sticky="w", pady=(0, 6))
        self._register_widget("check.test_mode", self.test_mode_check, "checkbutton", "テストモード")

        self.status_label = ttk.Label(test_frame, textvariable=self.state.status_var)
        self.status_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self._register_widget("label.status", self.status_label, "label", "状態表示")

        main_button_frame = ttk.Frame(actions_frame)
        main_button_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 6))
        self._register_widget("frame.main_buttons", main_button_frame, "frame", "主要ボタン群")
        tool_button_frame = ttk.Frame(test_frame)
        tool_button_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 0))
        self._register_widget("frame.tool_buttons", tool_button_frame, "frame", "テスト支援ボタン群")

        self._main_buttons = []
        primary_button_defs = [
            ("button.init_db", "DB初期化", self._handle_init_db),
            ("button.ingest", "DBへ登録", self._handle_ingest),
            ("button.plot", "グラフ出力", self._handle_plot),
        ]
        utility_button_defs = [
            ("button.save_test_context", "状態保存", self._handle_save_test_context),
            ("button.save_widget_tree", "ウィジェット保存", self._handle_save_widget_tree),
            ("button.save_screenshot", "画面を保存", self._handle_save_screenshot),
            ("button.save_log", "ログを保存", self._handle_save_log),
        ]
        for index, (widget_id, label, command) in enumerate(primary_button_defs):
            button = ttk.Button(main_button_frame, text=label, command=command)
            button.grid(row=0, column=index, sticky="ew", padx=(0, 8), pady=(0, 4))
            main_button_frame.columnconfigure(index, weight=1)
            self._register_widget(widget_id, button, "button", label)
            self._main_buttons.append(button)
        for index, (widget_id, label, command) in enumerate(utility_button_defs):
            button = ttk.Button(tool_button_frame, text=label, command=command)
            button.grid(row=index // 2, column=index % 2, sticky="ew", padx=(0, 8), pady=(0, 4))
            tool_button_frame.columnconfigure(index % 2, weight=1)
            self._register_widget(widget_id, button, "button", label)
            self._main_buttons.append(button)

    def _build_candidate_area(self, frame: ttk.LabelFrame) -> None:
        """候補セルテーブルと面ビューを構築する。"""
        self.view_notebook = ttk.Notebook(frame)
        self.view_notebook.grid(row=0, column=0, sticky="nsew")
        self._register_widget("notebook.views", self.view_notebook, "notebook", "候補・面ビュー")

        table_tab = ttk.Frame(self.view_notebook)
        table_tab.columnconfigure(0, weight=1)
        table_tab.rowconfigure(1, weight=1)
        self._register_widget("tab.candidate_table", table_tab, "tab", "候補セル表")

        spatial_tab = ttk.Frame(self.view_notebook)
        spatial_tab.columnconfigure(0, weight=1)
        spatial_tab.rowconfigure(1, weight=1)
        self._register_widget("tab.spatial_view", spatial_tab, "tab", "面ビュー")

        self.view_notebook.add(table_tab, text="候補セル表")
        self.view_notebook.add(spatial_tab, text="面ビュー")

        table_toolbar = ttk.Frame(table_tab)
        table_toolbar.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 2))
        table_toolbar.columnconfigure(1, weight=1)
        self._register_widget("frame.candidate_toolbar", table_toolbar, "frame", "候補セル表操作")
        candidate_refresh_button = ttk.Button(table_toolbar, text="候補更新", command=self._handle_list_candidates)
        candidate_refresh_button.grid(row=0, column=0, sticky="w")
        self._register_widget("button.list_candidates", candidate_refresh_button, "button", "候補更新")
        self._main_buttons.append(candidate_refresh_button)
        self.candidate_summary_label = ttk.Label(table_toolbar, text="候補セル 未取得")
        self.candidate_summary_label.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self._register_widget("label.candidate_summary", self.candidate_summary_label, "label", "候補セル概要")

        columns = ("流域名", "流域内行", "流域内列", "中心X", "中心Y", "重なり率", "データセット数")
        self.candidate_tree = ttk.Treeview(table_tab, columns=columns, show="headings", height=14)
        self.candidate_tree.grid(row=1, column=0, sticky="nsew")
        self._register_widget("tree.candidates", self.candidate_tree, "treeview", "候補セル一覧")
        for name in columns:
            self.candidate_tree.heading(name, text=name)
            width = 110 if name == "流域名" else 90
            if name in {"中心X", "中心Y"}:
                width = 130
            self.candidate_tree.column(name, width=width, stretch=True, anchor="center")
        scrollbar = ttk.Scrollbar(table_tab, orient="vertical", command=self.candidate_tree.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.candidate_tree.configure(yscrollcommand=scrollbar.set)
        self.candidate_tree.bind("<<TreeviewSelect>>", self._on_candidate_selected)

        self._build_spatial_area(spatial_tab)

    def _build_spatial_area(self, frame: ttk.Frame) -> None:
        """面ビュータブを構築する。"""
        control_frame = ttk.Frame(frame)
        control_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 2))
        control_frame.columnconfigure(1, weight=1)
        control_frame.columnconfigure(3, weight=1)
        self._register_widget("frame.spatial_controls", control_frame, "frame", "面ビュー操作")

        self._build_timestamp_selector(
            control_frame,
            row=0,
            label_text="面ビュー時刻",
            prefix="spatial",
            year_var=self.state.spatial_year_var,
            month_var=self.state.spatial_month_var,
            day_var=self.state.spatial_day_var,
            time_var=self.state.spatial_time_var,
            on_change=self._on_spatial_timestamp_changed,
        )
        self.spatial_metric_combo = add_labeled_combobox(
            control_frame,
            row=1,
            label_text="面ビュー指標",
            variable=self.state.spatial_metric_var,
            values=list(SPATIAL_METRIC_LABELS.values()),
            widget_id="combobox.spatial_metric",
            register_widget=self._register_widget,
            width=22,
        )
        render_button = ttk.Button(control_frame, text="面を描画", command=self._handle_render_spatial_view)
        render_button.grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
        self._register_widget("button.render_spatial_view", render_button, "button", "面を描画")
        self._main_buttons.append(render_button)
        clear_button = ttk.Button(control_frame, text="選択解除", command=self._clear_spatial_selection)
        clear_button.grid(row=2, column=1, sticky="w", padx=(0, 8), pady=(6, 0))
        self._register_widget("button.clear_spatial_selection", clear_button, "button", "選択解除")
        self._main_buttons.append(clear_button)
        self.spatial_status_label = ttk.Label(control_frame, text="")
        self.spatial_status_label.grid(row=2, column=2, columnspan=2, sticky="w", pady=(6, 0))
        self._register_widget("label.spatial_status", self.spatial_status_label, "label", "面ビュー状態")

        canvas_frame = ttk.Frame(frame)
        canvas_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 6))
        canvas_frame.columnconfigure(0, weight=1)
        canvas_frame.rowconfigure(0, weight=1)
        self._register_widget("frame.spatial_canvas", canvas_frame, "frame", "面ビュー描画枠")

        self.spatial_figure = Figure(figsize=(8.0, 5.4), dpi=100)
        self.spatial_ax = self.spatial_figure.add_subplot(111)
        self.spatial_canvas = FigureCanvasTkAgg(self.spatial_figure, master=canvas_frame)
        self.spatial_canvas.draw()
        self.spatial_canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        self._register_widget("canvas.spatial_view", self.spatial_canvas.get_tk_widget(), "canvas", "面ビュー")
        self.spatial_canvas.mpl_connect("button_press_event", self._on_spatial_canvas_click)

    def _build_log_area(self, frame: ttk.LabelFrame) -> None:
        """ログエリアを構築する。"""
        self.log_text = add_scrolled_log(frame, widget_id="text.log", register_widget=self._register_widget, height=10)
        self.log_text.configure(state="disabled")

    def _build_timestamp_selector(
        self,
        parent: ttk.Frame,
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
        self._register_widget(f"label.{prefix}_timestamp", label, "label", label_text)

        holder = ttk.Frame(parent)
        holder.grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=2)
        holder.columnconfigure(0, weight=1)
        holder.columnconfigure(1, weight=1)
        holder.columnconfigure(2, weight=1)
        holder.columnconfigure(3, weight=1)
        self._register_widget(f"frame.{prefix}_timestamp", holder, "frame", f"{label_text}選択")

        year_combo = ttk.Combobox(holder, textvariable=year_var, values=[], width=8, state="readonly")
        year_combo.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self._register_widget(f"combobox.{prefix}_year", year_combo, "combobox", f"{label_text}年")
        year_combo.bind("<<ComboboxSelected>>", lambda _event: on_change("year"))

        month_combo = ttk.Combobox(holder, textvariable=month_var, values=[], width=6, state="readonly")
        month_combo.grid(row=0, column=1, sticky="ew", padx=(0, 4))
        self._register_widget(f"combobox.{prefix}_month", month_combo, "combobox", f"{label_text}月")
        month_combo.bind("<<ComboboxSelected>>", lambda _event: on_change("month"))

        day_combo = ttk.Combobox(holder, textvariable=day_var, values=[], width=6, state="readonly")
        day_combo.grid(row=0, column=2, sticky="ew", padx=(0, 4))
        self._register_widget(f"combobox.{prefix}_day", day_combo, "combobox", f"{label_text}日")
        day_combo.bind("<<ComboboxSelected>>", lambda _event: on_change("day"))

        time_combo = ttk.Combobox(holder, textvariable=time_var, values=[], width=8, state="readonly")
        time_combo.grid(row=0, column=3, sticky="ew")
        self._register_widget(f"combobox.{prefix}_time", time_combo, "combobox", f"{label_text}時刻")
        time_combo.bind("<<ComboboxSelected>>", lambda _event: on_change("time"))

        setattr(self, f"{prefix}_year_combo", year_combo)
        setattr(self, f"{prefix}_month_combo", month_combo)
        setattr(self, f"{prefix}_day_combo", day_combo)
        setattr(self, f"{prefix}_time_combo", time_combo)

    def _register_widget(self, widget_id: str, widget: tk.Widget, role: str, display_name: str) -> None:
        """AI テスト向けの widget registry へ登録する。"""
        self.state.widget_registry[widget_id] = {
            "widget": widget,
            "role": role,
            "display_name": display_name,
        }

    def _apply_cached_input_paths(self) -> None:
        """設定キャッシュ上の入力パスを一覧へ反映する。"""
        self.state.input_paths = list(self.state.input_paths)
        self._set_listbox_items(self.input_paths_listbox, [_display_input_path(path) for path in self.state.input_paths])

    def _enqueue_log_line(self, message: str) -> None:
        """どのスレッドからでも GUI ログ追記を要求できるようにする。"""
        self._ui_queue.put(("log", message))

    def _append_log_line(self, message: str) -> None:
        """ログ欄と内部ログ配列へ 1 行追記する。"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"{timestamp} {message}"
        self.state.log_lines.append(line)
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _process_ui_queue(self) -> None:
        """バックグラウンド処理と logging からの UI 更新要求を処理する。"""
        try:
            while True:
                item = self._ui_queue.get_nowait()
                kind = item[0]
                if kind == "log":
                    self._append_log_line(str(item[1]))
                    continue
                if kind == "task_success":
                    _, action_name, result, callback = item
                    try:
                        callback(result)
                    except Exception as exc:
                        self._record_last_run(action=action_name, success=False, error=str(exc))
                        self._show_error("処理結果の反映に失敗しました。", detail=str(exc))
                    finally:
                        self._busy_action = None
                        self._set_busy(False, "待機中")
                    continue
                if kind == "task_error":
                    _, action_name, error_message, user_message = item
                    self._record_last_run(action=action_name, success=False, error=error_message)
                    self._show_error(user_message, detail=error_message)
                    self._busy_action = None
                    self._set_busy(False, "待機中")
                    continue
        except Empty:
            pass
        finally:
            self.root.after(120, self._process_ui_queue)

    def _set_status(self, text: str) -> None:
        """状態ラベルを更新する。"""
        self.state.status_var.set(text)
        self.root.update_idletasks()

    def _set_text_widget(self, widget: tk.Text, value: str) -> None:
        """Text ウィジェットを全置換する。"""
        widget.delete("1.0", "end")
        widget.insert("1.0", value)

    def _set_listbox_items(self, widget: tk.Listbox, items: list[str]) -> None:
        """Listbox の内容を全置換する。"""
        widget.delete(0, "end")
        for item in items:
            widget.insert("end", item)

    def _get_input_paths(self) -> list[str]:
        """入力パス一覧からパス群を取得する。"""
        return list(self.state.input_paths)

    def _refresh_control_states(self) -> None:
        """系列モードや入力件数に応じて UI の有効/無効を切り替える。"""
        series_mode = self.state.get_series_mode()
        local_state = "normal" if series_mode == "cell" else "disabled"
        self.local_row_combo.configure(state="readonly" if series_mode == "cell" else "disabled")
        self.local_col_combo.configure(state="readonly" if series_mode == "cell" else "disabled")
        input_count = len(self._get_input_paths())
        self.ingest_dataset_entry.configure(state="normal" if input_count <= 1 else "disabled")
        self._update_test_summary()

    def _merge_input_paths(self, new_paths: list[str]) -> None:
        """入力パスを重複排除しつつ一覧へ反映する。"""
        paths = list(dict.fromkeys(self._get_input_paths() + new_paths))
        self.state.input_paths = paths
        self._set_listbox_items(self.input_paths_listbox, [_display_input_path(path) for path in paths])
        self._refresh_control_states()

    def _remove_selected_input_paths(self) -> None:
        """選択中の入力パスだけを削除する。"""
        selected = list(self.input_paths_listbox.curselection())
        if not selected:
            return
        current = list(self.state.input_paths)
        for index in reversed(selected):
            self.input_paths_listbox.delete(index)
            current.pop(index)
        self.state.input_paths = current
        self._refresh_control_states()

    def _load_db_metadata(self) -> None:
        """DB から流域名とデータセット候補を読み込む。"""
        db_path = self.state.db_path_var.get().strip()
        polygon_values: list[str] = []
        dataset_values: list[str] = []
        if db_path and Path(db_path).exists():
            cached = self._db_metadata_cache.get(db_path)
            if cached is not None:
                polygon_values, dataset_values = cached
            else:
                try:
                    with open_db(db_path) as conn:
                        polygon_rows = conn.execute("SELECT polygon_name FROM polygons ORDER BY polygon_name").fetchall()
                        dataset_rows = conn.execute("SELECT dataset_id FROM datasets ORDER BY dataset_id").fetchall()
                    polygon_values = [str(row[0]) for row in polygon_rows]
                    dataset_values = [str(row[0]) for row in dataset_rows]
                    self._db_metadata_cache[db_path] = (polygon_values, dataset_values)
                except Exception as exc:
                    LOGGER.warning("DB メタデータの読込に失敗しました: %s", exc)
        self.polygon_name_combo.configure(values=polygon_values)
        self.preferred_dataset_combo.configure(values=[ALL_DATASETS_LABEL] + dataset_values)
        if self.state.polygon_name_var.get().strip() and self.state.polygon_name_var.get().strip() not in polygon_values:
            self.state.polygon_name_var.set("")
        current_dataset = self.state.preferred_dataset_id_var.get().strip()
        if not current_dataset:
            self.state.preferred_dataset_id_var.set(ALL_DATASETS_LABEL)
        elif current_dataset != ALL_DATASETS_LABEL and current_dataset not in dataset_values:
            self.state.preferred_dataset_id_var.set(ALL_DATASETS_LABEL)
        self._load_time_candidates()

    def _get_preferred_dataset_id(self) -> str | None:
        """GUI 表示値から内部の優先 dataset_id を返す。"""
        value = self.state.preferred_dataset_id_var.get().strip()
        if not value or value == ALL_DATASETS_LABEL:
            return None
        return value

    def _invalidate_db_related_caches(self, db_path: str | None = None) -> None:
        """DB に依存するキャッシュを破棄する。"""
        if not db_path:
            self._db_metadata_cache.clear()
            self._time_candidates_cache.clear()
            self._candidate_frame_cache.clear()
            return
        self._db_metadata_cache.pop(db_path, None)
        for cache in (self._time_candidates_cache, self._candidate_frame_cache):
            keys = [key for key in cache if key[0] == db_path]
            for key in keys:
                cache.pop(key, None)

    def _load_time_candidates(self) -> None:
        """現在の DB / 流域 / 優先 dataset に応じて日時候補を読む。"""
        db_path = self.state.db_path_var.get().strip()
        polygon_name = self.state.polygon_name_var.get().strip()
        dataset_id = self._get_preferred_dataset_id()
        timestamps: list[pd.Timestamp] = []
        cache_key = (db_path, polygon_name, dataset_id)
        if db_path and Path(db_path).exists() and polygon_name:
            cached = self._time_candidates_cache.get(cache_key)
            if cached is not None:
                timestamps = cached
            else:
                try:
                    with open_db(db_path) as conn:
                        sql = """
                        SELECT DISTINCT ct.observed_at
                        FROM cell_timeseries ct
                        JOIN polygon_cell_map pcm
                          ON pcm.dataset_id = ct.dataset_id AND pcm.row = ct.row AND pcm.col = ct.col
                        JOIN polygons p ON p.polygon_id = pcm.polygon_id
                        WHERE p.polygon_name = ?
                        """
                        params: list[object] = [polygon_name]
                        if dataset_id is not None:
                            sql += " AND ct.dataset_id = ?"
                            params.append(dataset_id)
                        sql += " ORDER BY ct.observed_at"
                        rows = conn.execute(sql, params).fetchall()
                    timestamps = [pd.Timestamp(str(row[0])) for row in rows]
                    self._time_candidates_cache[cache_key] = timestamps
                except Exception as exc:
                    LOGGER.warning("日時候補の読込に失敗しました: %s", exc)
        self._populate_timestamp_selector(
            prefix="view_start",
            timestamps=timestamps,
            year_var=self.state.view_start_year_var,
            month_var=self.state.view_start_month_var,
            day_var=self.state.view_start_day_var,
            time_var=self.state.view_start_time_var,
            target_var=self.state.view_start_var,
            default="first",
        )
        self._populate_timestamp_selector(
            prefix="view_end",
            timestamps=timestamps,
            year_var=self.state.view_end_year_var,
            month_var=self.state.view_end_month_var,
            day_var=self.state.view_end_day_var,
            time_var=self.state.view_end_time_var,
            target_var=self.state.view_end_var,
            default="last",
        )
        self._populate_timestamp_selector(
            prefix="spatial",
            timestamps=timestamps,
            year_var=self.state.spatial_year_var,
            month_var=self.state.spatial_month_var,
            day_var=self.state.spatial_day_var,
            time_var=self.state.spatial_time_var,
            target_var=self.state.spatial_timestamp_var,
            default="first",
        )

    def _populate_timestamp_selector(
        self,
        *,
        prefix: str,
        timestamps: list[pd.Timestamp],
        year_var: tk.StringVar,
        month_var: tk.StringVar,
        day_var: tk.StringVar,
        time_var: tk.StringVar,
        target_var: tk.StringVar,
        default: str,
    ) -> None:
        """1つの timestamp selector に候補を流し込む。"""
        year_combo: ttk.Combobox = getattr(self, f"{prefix}_year_combo")
        month_combo: ttk.Combobox = getattr(self, f"{prefix}_month_combo")
        day_combo: ttk.Combobox = getattr(self, f"{prefix}_day_combo")
        time_combo: ttk.Combobox = getattr(self, f"{prefix}_time_combo")
        if not timestamps:
            year_combo.configure(values=[])
            month_combo.configure(values=[])
            day_combo.configure(values=[])
            time_combo.configure(values=[])
            year_var.set("")
            month_var.set("")
            day_var.set("")
            time_var.set("")
            target_var.set("")
            return

        years = sorted({ts.strftime("%Y") for ts in timestamps})
        if year_var.get() not in years:
            year_var.set(years[0] if default == "first" else years[-1])

        months = sorted({ts.strftime("%m") for ts in timestamps if ts.strftime("%Y") == year_var.get()})
        if month_var.get() not in months:
            month_var.set(months[0] if default == "first" else months[-1])

        days = sorted(
            {
                ts.strftime("%d")
                for ts in timestamps
                if ts.strftime("%Y") == year_var.get() and ts.strftime("%m") == month_var.get()
            }
        )
        if day_var.get() not in days:
            day_var.set(days[0] if default == "first" else days[-1])

        times = sorted(
            {
                ts.strftime("%H:%M")
                for ts in timestamps
                if ts.strftime("%Y") == year_var.get()
                and ts.strftime("%m") == month_var.get()
                and ts.strftime("%d") == day_var.get()
            }
        )
        if time_var.get() not in times:
            time_var.set(times[0] if times and default == "first" else (times[-1] if times else ""))

        year_combo.configure(values=years)
        month_combo.configure(values=months)
        day_combo.configure(values=days)
        time_combo.configure(values=times)
        target_var.set(_compose_timestamp(year_var.get(), month_var.get(), day_var.get(), time_var.get()))

    def _sync_timestamp_var(
        self,
        *,
        year_var: tk.StringVar,
        month_var: tk.StringVar,
        day_var: tk.StringVar,
        time_var: tk.StringVar,
        target_var: tk.StringVar,
    ) -> None:
        """選択中の年 / 月 / 日 / 時刻から ISO 文字列を反映する。"""
        target_var.set(_compose_timestamp(year_var.get(), month_var.get(), day_var.get(), time_var.get()))

    def _on_view_start_changed(self, changed_part: str) -> None:
        """開始日時の年/日/時刻変更を反映する。"""
        if changed_part in {"year", "month", "day"}:
            self._load_time_candidates()
        self._sync_timestamp_var(
            year_var=self.state.view_start_year_var,
            month_var=self.state.view_start_month_var,
            day_var=self.state.view_start_day_var,
            time_var=self.state.view_start_time_var,
            target_var=self.state.view_start_var,
        )
        self._validate_datetime_inputs_inline()
        self._update_test_summary()

    def _on_view_end_changed(self, changed_part: str) -> None:
        """終了日時の年/日/時刻変更を反映する。"""
        if changed_part in {"year", "month", "day"}:
            self._load_time_candidates()
        self._sync_timestamp_var(
            year_var=self.state.view_end_year_var,
            month_var=self.state.view_end_month_var,
            day_var=self.state.view_end_day_var,
            time_var=self.state.view_end_time_var,
            target_var=self.state.view_end_var,
        )
        self._validate_datetime_inputs_inline()
        self._update_test_summary()

    def _on_spatial_timestamp_changed(self, changed_part: str) -> None:
        """面ビュー時刻の年/日/時刻変更を反映する。"""
        if changed_part in {"year", "month", "day"}:
            self._load_time_candidates()
        self._sync_timestamp_var(
            year_var=self.state.spatial_year_var,
            month_var=self.state.spatial_month_var,
            day_var=self.state.spatial_day_var,
            time_var=self.state.spatial_time_var,
            target_var=self.state.spatial_timestamp_var,
        )
        self._validate_spatial_timestamp_inline()
        self._update_test_summary()

    def _load_candidate_cell_choices(self) -> None:
        """候補セル一覧から流域内行列の選択候補を作る。"""
        if self.state.candidate_frame.empty:
            self.local_row_combo.configure(values=[])
            self.local_col_combo.configure(values=[])
            return
        row_values = sorted({str(int(value)) for value in self.state.candidate_frame["polygon_local_row"].dropna().tolist()})
        col_values = sorted({str(int(value)) for value in self.state.candidate_frame["polygon_local_col"].dropna().tolist()})
        self.local_row_combo.configure(values=row_values)
        self.local_col_combo.configure(values=col_values)
        if self.state.local_row_var.get().strip() and self.state.local_row_var.get().strip() not in row_values:
            self.state.local_row_var.set("")
        if self.state.local_col_var.get().strip() and self.state.local_col_var.get().strip() not in col_values:
            self.state.local_col_var.set("")

    def _set_entry_validity(self, widget: tk.Widget, *, valid: bool) -> None:
        """簡易な入力妥当性表示を反映する。"""
        color = "#b00020" if not valid else "#888888"
        if isinstance(widget, (tk.Text, tk.Listbox)):
            widget.configure(highlightthickness=1, highlightbackground=color, highlightcolor=color)
            return
        try:
            widget.configure(foreground=("#b00020" if not valid else "black"))
        except tk.TclError:
            pass

    def _validate_db_path_inline(self) -> bool:
        """DB パスの軽い事前検証を行う。"""
        db_path = self.state.db_path_var.get().strip()
        if not db_path:
            self.io_validation_label.configure(text="データベース保存先を指定してください。")
            self._set_entry_validity(self.db_entry, valid=False)
            return False
        self.io_validation_label.configure(text="" if Path(db_path).exists() else "未作成の DB です。初期化または既存 DB 指定が必要です。")
        self._set_entry_validity(self.db_entry, valid=True)
        return True

    def _validate_input_paths_inline(self) -> bool:
        """入力パス欄の存在チェックを行う。"""
        paths = self._get_input_paths()
        if not paths:
            self._set_entry_validity(self.input_paths_listbox, valid=True)
            return True
        missing = [path for path in paths if not Path(path).exists()]
        if missing:
            self.io_validation_label.configure(text=f"取り込み対象が見つかりません: {missing[0]}")
            self._set_entry_validity(self.input_paths_listbox, valid=False)
            return False
        self._set_entry_validity(self.input_paths_listbox, valid=True)
        if "見つかりません" in self.io_validation_label.cget("text"):
            self.io_validation_label.configure(text="")
        return True

    def _validate_out_dir_inline(self) -> bool:
        """出力先フォルダの軽い検証を行う。"""
        out_dir = self.state.out_dir_var.get().strip()
        if not out_dir:
            self._set_entry_validity(self.out_dir_entry, valid=True)
            return True
        parent = Path(out_dir).parent
        valid = parent.exists()
        self._set_entry_validity(self.out_dir_entry, valid=valid)
        if not valid:
            self.io_validation_label.configure(text=f"出力先の親フォルダが存在しません: {parent}")
        elif "出力先" in self.io_validation_label.cget("text"):
            self.io_validation_label.configure(text="")
        return valid

    def _validate_datetime_inputs_inline(self) -> bool:
        """日時入力の整形式チェックを行う。"""
        start_raw = self.state.view_start_var.get().strip()
        end_raw = self.state.view_end_var.get().strip()
        ok = True
        for widgets, raw in (
            ((self.view_start_year_combo, self.view_start_day_combo, self.view_start_time_combo), start_raw),
            ((self.view_end_year_combo, self.view_end_day_combo, self.view_end_time_combo), end_raw),
        ):
            if not raw:
                for widget in widgets:
                    self._set_entry_validity(widget, valid=True)
                continue
            try:
                _parse_datetime(raw)
                for widget in widgets:
                    self._set_entry_validity(widget, valid=True)
            except Exception:
                for widget in widgets:
                    self._set_entry_validity(widget, valid=False)
                self.params_validation_label.configure(text="日時は YYYY-MM-DDTHH:MM:SS 形式で入力してください。")
                ok = False
        if ok and start_raw and end_raw:
            try:
                if _parse_datetime(start_raw) > _parse_datetime(end_raw):
                    self.params_validation_label.configure(text="表示開始日時は表示終了日時以前である必要があります。")
                    for widget in (self.view_start_year_combo, self.view_start_day_combo, self.view_start_time_combo):
                        self._set_entry_validity(widget, valid=False)
                    for widget in (self.view_end_year_combo, self.view_end_day_combo, self.view_end_time_combo):
                        self._set_entry_validity(widget, valid=False)
                    return False
            except Exception:
                return False
        if ok:
            self.params_validation_label.configure(text="")
        return ok

    def _validate_spatial_timestamp_inline(self) -> bool:
        """面ビュー時刻の整形式チェックを行う。"""
        value = self.state.spatial_timestamp_var.get().strip()
        if not value:
            self.spatial_status_label.configure(text="面ビュー時刻を指定してください。")
            for widget in (self.spatial_year_combo, self.spatial_day_combo, self.spatial_time_combo):
                self._set_entry_validity(widget, valid=False)
            return False
        try:
            _parse_datetime(value)
        except Exception:
            self.spatial_status_label.configure(text="面ビュー時刻は YYYY-MM-DDTHH:MM:SS 形式で入力してください。")
            for widget in (self.spatial_year_combo, self.spatial_day_combo, self.spatial_time_combo):
                self._set_entry_validity(widget, valid=False)
            return False
        for widget in (self.spatial_year_combo, self.spatial_day_combo, self.spatial_time_combo):
            self._set_entry_validity(widget, valid=True)
        return True

    def _on_db_path_changed(self) -> None:
        """DB パス変更時に入力検証と候補再読込を行う。"""
        self._invalidate_db_related_caches()
        self._validate_db_path_inline()
        self._load_db_metadata()
        self._update_test_summary()

    def _on_polygon_name_changed(self) -> None:
        """流域名変更時に候補テーブルの旧表示を無効化する。"""
        self.state.candidate_frame = self.state.candidate_frame.iloc[0:0].copy()
        self._candidate_items.clear()
        for item_id in self.candidate_tree.get_children():
            self.candidate_tree.delete(item_id)
        self.candidate_summary_label.configure(text="候補セル 未取得")
        self._load_time_candidates()
        self._load_candidate_cell_choices()
        self._update_test_summary()

    def _on_preferred_dataset_changed(self) -> None:
        """優先データセット変更時に日時候補を再読込する。"""
        self._load_time_candidates()
        self._update_test_summary()

    def _start_background_task(
        self,
        *,
        action_name: str,
        busy_text: str,
        user_error_message: str,
        worker,
        on_success,
    ) -> None:
        """長時間処理をバックグラウンドで実行する。"""
        if self._busy_action is not None:
            raise RuntimeError("別の処理を実行中です。")
        self._busy_action = action_name
        self._set_busy(True, busy_text)

        def task() -> None:
            try:
                result = worker()
            except Exception as exc:
                self._ui_queue.put(("task_error", action_name, str(exc), user_error_message))
            else:
                self._ui_queue.put(("task_success", action_name, result, on_success))

        threading.Thread(target=task, daemon=True, name=f"uc-rainfall-{action_name}").start()

    def _update_test_summary(self) -> None:
        """現在状態サマリを内部更新する。"""
        self.state.current_summary = {
            "db_path": self.state.db_path_var.get().strip(),
            "input_paths": self._get_input_paths(),
            "polygon_dir": self.state.polygon_dir_var.get().strip(),
            "ingest_dataset_id": self.state.ingest_dataset_id_var.get().strip(),
            "preferred_dataset_id": self.state.preferred_dataset_id_var.get().strip(),
            "polygon_name": self.state.polygon_name_var.get().strip(),
            "series_mode": self.state.get_series_mode(),
            "local_row": self.state.local_row_var.get().strip(),
            "local_col": self.state.local_col_var.get().strip(),
            "view_start": self.state.view_start_var.get().strip(),
            "view_end": self.state.view_end_var.get().strip(),
            "out_dir": self.state.out_dir_var.get().strip(),
            "spatial_timestamp": self.state.spatial_timestamp_var.get().strip(),
            "spatial_metric": self.state.get_spatial_metric(),
            "test_mode": bool(self.state.test_mode_var.get()),
            "candidate_count": int(len(self.state.candidate_frame)),
            "spatial_selected_cell": None if self._spatial_payload is None else self._spatial_payload.get("selected_cell"),
        }

    def _collect_widget_tree(self) -> dict[str, Any]:
        """登録済み widget の機械可読スナップショットを構築する。"""
        self.root.update_idletasks()
        widgets: list[dict[str, Any]] = []
        for widget_id, info in self.state.widget_registry.items():
            widget = info["widget"]
            try:
                geometry = {
                    "x": widget.winfo_rootx(),
                    "y": widget.winfo_rooty(),
                    "width": widget.winfo_width(),
                    "height": widget.winfo_height(),
                }
                requested = {
                    "width": widget.winfo_reqwidth(),
                    "height": widget.winfo_reqheight(),
                }
            except tk.TclError:
                geometry = {"x": None, "y": None, "width": None, "height": None}
                requested = {"width": None, "height": None}
            extra: dict[str, Any] = {}
            if isinstance(widget, ttk.Treeview):
                extra["treeview"] = self._get_treeview_meta(widget)
            widgets.append(
                {
                    "widget_id": widget_id,
                    "role": info["role"],
                    "display_name": info["display_name"],
                    "class_name": widget.winfo_class() if widget.winfo_exists() else None,
                    "visible": bool(widget.winfo_ismapped()) if widget.winfo_exists() else False,
                    "enabled": self._is_widget_enabled(widget),
                    "value": self._get_widget_value(widget),
                    "geometry": geometry,
                    "requested_geometry": requested,
                    "overflow_hint": self._has_overflow_hint(geometry, requested),
                    "text_length": len(str(self._get_widget_value(widget) or "")),
                    **extra,
                }
            )
        return {
            "saved_at": datetime.now(),
            "test_mode": bool(self.state.test_mode_var.get()),
            "window_geometry": {
                "width": self.root.winfo_width(),
                "height": self.root.winfo_height(),
                "requested_width": self.root.winfo_reqwidth(),
                "requested_height": self.root.winfo_reqheight(),
            },
            "spatial_view": self._build_spatial_view_meta(),
            "widgets": widgets,
        }

    def _build_spatial_view_meta(self) -> dict[str, Any]:
        """面ビューの現在状態を返す。"""
        if self._spatial_payload is None:
            return {
                "rendered": False,
                "selected_cell": None,
                "metric": self.state.get_spatial_metric(),
                "timestamp": self.state.spatial_timestamp_var.get().strip(),
            }
        return {
            "rendered": True,
            "dataset_id": self._spatial_payload.get("dataset_id"),
            "candidate_dataset_ids": self._spatial_payload.get("candidate_dataset_ids"),
            "polygon_name": self._spatial_payload.get("polygon_name"),
            "metric": self._spatial_payload.get("metric"),
            "timestamp": self._spatial_payload.get("observed_at").isoformat(timespec="seconds"),
            "selected_cell": self._spatial_payload.get("selected_cell"),
            "value_label": self._spatial_payload.get("value_label"),
            "cell_count": len(self._spatial_payload.get("cells", [])),
        }

    def _has_overflow_hint(self, geometry: dict[str, Any], requested: dict[str, Any]) -> bool:
        """要求サイズより実サイズが小さい場合のヒントを返す。"""
        width = geometry.get("width")
        height = geometry.get("height")
        req_width = requested.get("width")
        req_height = requested.get("height")
        if width is None or height is None or req_width is None or req_height is None:
            return False
        return bool(width < req_width or height < req_height)

    def _get_treeview_meta(self, widget: ttk.Treeview) -> dict[str, Any]:
        """Treeview の列情報と可視行情報を返す。"""
        columns = []
        for column_id in widget["columns"]:
            column_key = str(column_id)
            columns.append(
                {
                    "column_id": column_key,
                    "heading": str(widget.heading(column_key).get("text", "")),
                    "width": int(widget.column(column_key, "width")),
                    "minwidth": int(widget.column(column_key, "minwidth")),
                    "stretch": bool(widget.column(column_key, "stretch")),
                    "anchor": str(widget.column(column_key, "anchor")),
                }
            )
        visible_rows: list[dict[str, Any]] = []
        for item_id in widget.get_children():
            bbox = widget.bbox(item_id)
            if not bbox:
                continue
            visible_rows.append(
                {
                    "item_id": item_id,
                    "bbox": {"x": bbox[0], "y": bbox[1], "width": bbox[2], "height": bbox[3]},
                    "values": list(widget.item(item_id, "values")),
                }
            )
        selected_values = [list(widget.item(item_id, "values")) for item_id in widget.selection()]
        return {
            "columns": columns,
            "row_count": len(widget.get_children()),
            "visible_rows": visible_rows,
            "selected_values": selected_values,
        }

    def _save_context(self) -> Path:
        """現在状態スナップショットを保存する。"""
        self._update_test_summary()
        payload = {
            "saved_at": datetime.now(),
            "current_summary": self.state.current_summary,
            "last_run_summary": self.state.last_run_summary,
            "spatial_view": self._build_spatial_view_meta(),
            "candidate_preview": self.state.candidate_frame.head(20).to_dict(orient="records")
            if not self.state.candidate_frame.empty
            else [],
        }
        return save_gui_context(payload)

    def _save_widget_tree(self) -> Path:
        """widget tree を保存する。"""
        return save_widget_tree(self._collect_widget_tree())

    def _save_log(self) -> Path:
        """ログ内容を保存する。"""
        return save_gui_log(self.state.log_lines)

    def _save_last_run(self) -> Path | None:
        """直近処理サマリを保存する。"""
        if not self.state.last_run_summary:
            return None
        return save_last_run(self.state.last_run_summary)

    def _save_screenshot(self) -> Path | None:
        """GUI スクリーンショットを保存する。"""
        path = get_last_screenshot_path()
        if self.state.test_mode_var.get():
            self.root.lift()
            self.root.attributes("-topmost", True)
        self.root.update()
        x = self.root.winfo_rootx()
        y = self.root.winfo_rooty()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        if width <= 0 or height <= 0:
            return None
        escaped_path = str(path).replace("'", "''")
        script = (
            "$ErrorActionPreference='Stop'; "
            "Add-Type -AssemblyName System.Drawing; "
            f"$bmp=New-Object System.Drawing.Bitmap {width},{height}; "
            "$gfx=[System.Drawing.Graphics]::FromImage($bmp); "
            f"$gfx.CopyFromScreen({x},{y},0,0,$bmp.Size); "
            f"$bmp.Save('{escaped_path}', [System.Drawing.Imaging.ImageFormat]::Png); "
            "$gfx.Dispose(); "
            "$bmp.Dispose()"
        )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                check=True,
                capture_output=True,
                text=True,
            )
        except Exception as exc:
            LOGGER.warning("画面保存に失敗しました: %s", exc)
            return None
        return path

    def _write_test_artifacts(self) -> None:
        """テスト用アーティファクトをまとめて更新する。"""
        try:
            self._save_context()
            self._save_widget_tree()
            if self.state.test_mode_var.get():
                self._save_screenshot()
        except Exception as exc:
            LOGGER.warning("テスト用アーティファクト更新に失敗しました: %s", exc)

    def _record_last_run(self, *, action: str, success: bool, outputs: list[str] | None = None, error: str | None = None) -> None:
        """直近処理サマリを内部保持し、保存する。"""
        self.state.last_run_summary = {
            "recorded_at": datetime.now(),
            "action": action,
            "success": success,
            "current_summary": self.state.current_summary,
            "outputs": outputs or [],
            "error": error,
        }
        self._save_last_run()

    def _show_error(self, message: str, *, detail: str | None = None) -> None:
        """ユーザー向けエラーダイアログを出す。"""
        LOGGER.error("%s%s", message, f" 詳細: {detail}" if detail else "")
        body = message if detail is None else f"{message}\n\n{detail}"
        self._show_dialog("エラー", body, level="error")

    def _show_info(self, message: str) -> None:
        """情報ダイアログを出す。"""
        LOGGER.info(message)
        self._show_dialog("情報", message, level="info")

    def _show_dialog(self, title: str, message: str, *, level: str) -> None:
        """通常時は messagebox、テストモード時は操作可能な Toplevel を出す。"""
        if not self.state.test_mode_var.get():
            if level == "error":
                messagebox.showerror(title, message)
            else:
                messagebox.showinfo(title, message)
            return
        self._open_test_dialog(title, message, level=level)

    def _open_test_dialog(self, title: str, message: str, *, level: str) -> None:
        """AI テストモード用の操作可能なダイアログを表示する。"""
        self._close_active_dialog()
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.attributes("-topmost", True)
        dialog.resizable(False, False)
        dialog.geometry("+520+180")
        dialog.columnconfigure(0, weight=1)
        self._active_dialog = dialog
        self._register_widget("dialog.active.window", dialog, "dialog", title)

        header = ttk.Label(dialog, text=title)
        header.grid(row=0, column=0, sticky="w", padx=16, pady=(14, 8))
        self._register_widget("dialog.active.header", header, "label", f"{title}見出し")

        body = ttk.Label(dialog, text=message, justify="left", wraplength=520)
        body.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 12))
        self._register_widget("dialog.active.message", body, "label", f"{title}本文")

        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=2, column=0, sticky="e", padx=16, pady=(0, 14))
        self._register_widget("dialog.active.buttons", button_frame, "frame", f"{title}ボタン群")
        close_button = ttk.Button(button_frame, text="閉じる", command=self._close_active_dialog)
        close_button.grid(row=0, column=0)
        self._register_widget("dialog.active.ok", close_button, "button", f"{title}閉じる")
        dialog.protocol("WM_DELETE_WINDOW", self._close_active_dialog)
        dialog.update_idletasks()

    def _close_active_dialog(self) -> None:
        """現在開いているテストモード用ダイアログを閉じる。"""
        dialog = self._active_dialog
        if dialog is None:
            return
        for widget_id in [
            "dialog.active.ok",
            "dialog.active.buttons",
            "dialog.active.message",
            "dialog.active.header",
            "dialog.active.window",
        ]:
            self.state.widget_registry.pop(widget_id, None)
        try:
            dialog.destroy()
        finally:
            self._active_dialog = None

    def _browse_db_path(self) -> None:
        """DB 保存先ファイルを選択する。"""
        path = filedialog.asksaveasfilename(
            title="データベース保存先を選択",
            defaultextension=".sqlite3",
            filetypes=[("SQLite", "*.sqlite3"), ("All Files", "*.*")],
        )
        if path:
            self.state.db_path_var.set(path)
            self._on_db_path_changed()

    def _browse_polygon_dir(self) -> None:
        """ポリゴンフォルダを選択する。"""
        path = filedialog.askdirectory(title="流域ポリゴンフォルダを選択")
        if path:
            self.state.polygon_dir_var.set(path)
            self._update_test_summary()

    def _browse_out_dir(self) -> None:
        """出力先フォルダを選択する。"""
        path = filedialog.askdirectory(title="出力先フォルダを選択")
        if path:
            self.state.out_dir_var.set(path)
            self._validate_out_dir_inline()
            self._update_test_summary()

    def _add_input_files(self) -> None:
        """ZIP ファイルを追加入力する。"""
        paths = filedialog.askopenfilenames(
            title="取り込み対象 ZIP を選択",
            filetypes=[("ZIP", "*.zip"), ("All Files", "*.*")],
        )
        if paths:
            self._merge_input_paths(list(paths))

    def _add_input_dir(self) -> None:
        """展開済みフォルダを追加入力する。"""
        path = filedialog.askdirectory(title="取り込み対象フォルダを選択")
        if path:
            self._merge_input_paths([path])

    def _clear_input_paths(self) -> None:
        """入力パス一覧をクリアする。"""
        self.state.input_paths = []
        self.input_paths_listbox.delete(0, "end")
        self._refresh_control_states()

    def _validate_db_path(self) -> str:
        """DB パス必須チェックを行う。"""
        db_path = self.state.db_path_var.get().strip()
        if not db_path:
            raise ValueError("データベース保存先を指定してください。")
        return db_path

    def _validate_polygon_name(self) -> str:
        """流域名必須チェックを行う。"""
        polygon_name = self.state.polygon_name_var.get().strip()
        if not polygon_name:
            raise ValueError("流域名を指定してください。")
        return polygon_name

    def _validate_plot_times(self) -> tuple[datetime, datetime]:
        """表示期間の入力を検証する。"""
        view_start_raw = self.state.view_start_var.get().strip()
        view_end_raw = self.state.view_end_var.get().strip()
        if not view_start_raw or not view_end_raw:
            raise ValueError("表示開始日時と表示終了日時を指定してください。")
        view_start = _parse_datetime(view_start_raw)
        view_end = _parse_datetime(view_end_raw)
        if view_start > view_end:
            raise ValueError("表示開始日時は表示終了日時以前である必要があります。")
        return view_start, view_end

    def _validate_input_paths(self) -> list[str]:
        """取り込み対象の存在チェックを行う。"""
        paths = self._get_input_paths()
        if not paths:
            raise ValueError("取り込み対象を1件以上指定してください。")
        missing = [path for path in paths if not Path(path).exists()]
        if missing:
            raise ValueError(f"取り込み対象が見つかりません: {missing[0]}")
        return paths

    def _set_busy(self, busy: bool, status: str) -> None:
        """実行中フラグを UI へ反映する。"""
        self._set_status(status)
        self.root.configure(cursor="watch" if busy else "")
        for button in self._main_buttons:
            button.configure(state="disabled" if busy else "normal")
        self.test_mode_check.configure(state="disabled" if busy else "normal")
        self.root.update_idletasks()

    def _persist_settings(self) -> None:
        """現在の主要入力を設定キャッシュへ保存する。"""
        update_settings(
            db_path=self.state.db_path_var.get().strip(),
            polygon_dir=self.state.polygon_dir_var.get().strip() or None,
            input_paths=self._get_input_paths(),
            dataset_id=self.state.ingest_dataset_id_var.get().strip() or None,
            preferred_dataset_id=self._get_preferred_dataset_id(),
            polygon_name=self.state.polygon_name_var.get().strip() or None,
            series_mode=self.state.get_series_mode(),
            view_start=self.state.view_start_var.get().strip() or None,
            view_end=self.state.view_end_var.get().strip() or None,
            out_dir=self.state.out_dir_var.get().strip() or None,
            spatial_timestamp=self.state.spatial_timestamp_var.get().strip() or None,
            spatial_metric=self.state.get_spatial_metric(),
            local_row=self.state.local_row_var.get().strip() or None,
            local_col=self.state.local_col_var.get().strip() or None,
        )

    def _populate_candidate_tree(self, frame: Any) -> None:
        """候補セルテーブルを再描画する。"""
        self.state.candidate_frame = frame.copy()
        self._candidate_items.clear()
        for item_id in self.candidate_tree.get_children():
            self.candidate_tree.delete(item_id)
        if frame.empty:
            self.candidate_summary_label.configure(text="候補セル 0 件")
            self._update_test_summary()
            return
        for _, row in frame.iterrows():
            item_id = self.candidate_tree.insert(
                "",
                "end",
                values=(
                    row.get("polygon_name", ""),
                    row.get("polygon_local_row", ""),
                    row.get("polygon_local_col", ""),
                    round(float(row.get("x_center", 0.0)), 6),
                    round(float(row.get("y_center", 0.0)), 6),
                    round(float(row.get("overlap_ratio", 0.0)), 3),
                    int(row.get("dataset_count", 0)),
                ),
            )
            self._candidate_items[item_id] = row.to_dict()
        self.candidate_summary_label.configure(text=f"候補セル {len(frame)} 件")
        self._load_candidate_cell_choices()
        self._update_test_summary()

    def _render_spatial_payload(self, payload: dict[str, Any]) -> None:
        """面ビュー描画を実行する。"""
        self._spatial_payload = payload
        self._spatial_payload.setdefault("selected_cell", None)
        self._spatial_cell_lookup = {}
        self._spatial_rectangles = []

        fig = self.spatial_figure
        ax = self.spatial_ax
        ax.clear()
        if self._spatial_colorbar is not None:
            try:
                self._spatial_colorbar.remove()
            except Exception:
                pass
            self._spatial_colorbar = None

        cells = payload["cells"]
        values = pd.to_numeric(cells["value"], errors="coerce")
        finite_values = values.dropna()
        if finite_values.empty:
            vmin, vmax = 0.0, 1.0
        else:
            vmin = float(finite_values.min())
            vmax = float(finite_values.max())
            if vmin == vmax:
                vmax = vmin + 1.0
        norm = Normalize(vmin=vmin, vmax=vmax)
        colormap = cm.get_cmap("Blues")

        for row in cells.itertuples(index=False):
            cell_info = row._asdict()
            rectangle = Rectangle(
                (float(cell_info["minx"]), float(cell_info["miny"])),
                float(cell_info["maxx"]) - float(cell_info["minx"]),
                float(cell_info["maxy"]) - float(cell_info["miny"]),
                facecolor=colormap(norm(float(cell_info["value"]))) if pd.notna(cell_info["value"]) else "#d0d0d0",
                edgecolor="#666666",
                linewidth=0.7,
            )
            ax.add_patch(rectangle)
            key = (int(cell_info["polygon_local_row"]), int(cell_info["polygon_local_col"]))
            self._spatial_cell_lookup[key] = cell_info
            self._spatial_rectangles.append((rectangle, cell_info))

        polygon_geometry = payload["polygon_geometry"]
        boundary = polygon_geometry.boundary
        geoms = getattr(boundary, "geoms", [boundary])
        for geom in geoms:
            try:
                xs, ys = geom.xy
                ax.plot(xs, ys, color="black", linewidth=1.4)
            except Exception:
                continue

        ax.set_aspect("equal")
        bounds = payload.get("view_bounds")
        if bounds:
            dx = max(bounds["maxx"] - bounds["minx"], 1.0)
            dy = max(bounds["maxy"] - bounds["miny"], 1.0)
            ax.set_xlim(bounds["minx"] - dx * 0.05, bounds["maxx"] + dx * 0.05)
            ax.set_ylim(bounds["miny"] - dy * 0.05, bounds["maxy"] + dy * 0.05)
        ax.set_xlabel("X")
        ax.set_ylabel("Y")
        ax.set_title(
            f"{payload['polygon_name']} {payload['metric']} {payload['observed_at'].strftime('%Y-%m-%d %H:%M')}",
            fontsize=11,
        )
        sm = cm.ScalarMappable(norm=norm, cmap=colormap)
        # ScalarMappable をカラーバー用に作る。
        sm.set_array([])
        self._spatial_colorbar = fig.colorbar(sm, ax=ax, pad=0.02, fraction=0.04, label=payload["value_label"])
        ax.autoscale_view()
        fig.tight_layout()
        self.spatial_canvas.draw_idle()
        self.view_notebook.select(self.view_notebook.tabs()[-1])
        self.spatial_status_label.configure(
            text=f"dataset={payload['dataset_id']} / cell数={len(cells)} / metric={payload['metric']}"
        )
        self._highlight_spatial_selected_cell()
        self._update_test_summary()

    def _highlight_spatial_selected_cell(self) -> None:
        """現在の selected_cell を面ビュー上で強調する。"""
        selected = None if self._spatial_payload is None else self._spatial_payload.get("selected_cell")
        for rectangle, info in self._spatial_rectangles:
            key = (int(info["polygon_local_row"]), int(info["polygon_local_col"]))
            if selected == key:
                rectangle.set_linewidth(2.4)
                rectangle.set_edgecolor("#d62728")
            else:
                rectangle.set_linewidth(0.7)
                rectangle.set_edgecolor("#666666")
        if self._spatial_rectangles:
            self.spatial_canvas.draw_idle()

    def _clear_spatial_selection(self) -> None:
        """面ビュー上の選択セルを解除する。"""
        if self._spatial_payload is None:
            return
        self._spatial_payload["selected_cell"] = None
        self._highlight_spatial_selected_cell()
        self._update_test_summary()

    def _on_spatial_canvas_click(self, event) -> None:
        """面ビュークリックでセル選択を反映する。"""
        if event.xdata is None or event.ydata is None or self._spatial_payload is None:
            return
        picked = None
        for _, info in self._spatial_rectangles:
            if (
                float(info["minx"]) <= float(event.xdata) <= float(info["maxx"])
                and float(info["miny"]) <= float(event.ydata) <= float(info["maxy"])
            ):
                picked = info
                break
        if picked is None:
            return
        self._apply_spatial_selected_cell(
            int(picked["polygon_local_row"]),
            int(picked["polygon_local_col"]),
        )

    def _apply_spatial_selected_cell(self, local_row: int, local_col: int) -> None:
        """面ビューの選択セルを入力欄へ反映する。"""
        self.state.local_row_var.set(str(local_row))
        self.state.local_col_var.set(str(local_col))
        if self._spatial_payload is not None:
            self._spatial_payload["selected_cell"] = (local_row, local_col)
        for item_id, row in self._candidate_items.items():
            if (
                int(row.get("polygon_local_row", -1)) == local_row
                and int(row.get("polygon_local_col", -1)) == local_col
            ):
                self.candidate_tree.selection_set(item_id)
                self.candidate_tree.focus(item_id)
                break
        self._highlight_spatial_selected_cell()
        self._update_test_summary()

    def _on_candidate_selected(self, _event: tk.Event[tk.Widget] | None = None) -> None:
        """候補セル選択を流域内行列へ反映する。"""
        selected = self.candidate_tree.selection()
        if not selected:
            return
        row = self._candidate_items.get(selected[0])
        if not row:
            return
        self.state.local_row_var.set(str(int(row["polygon_local_row"])))
        self.state.local_col_var.set(str(int(row["polygon_local_col"])))
        self.state.polygon_name_var.set(str(row["polygon_name"]))
        if self._spatial_payload is not None:
            self._spatial_payload["selected_cell"] = (
                int(row["polygon_local_row"]),
                int(row["polygon_local_col"]),
            )
            self._highlight_spatial_selected_cell()
        self._update_test_summary()

    def _handle_render_spatial_view(self) -> None:
        """面的可視化ビューを描画する。"""
        try:
            db_path = self._validate_db_path()
            polygon_name = self._validate_polygon_name()
            if not self._validate_spatial_timestamp_inline():
                raise ValueError("面ビュー時刻の入力を修正してください。")
            observed_at = _parse_datetime(self.state.spatial_timestamp_var.get().strip())
            metric = self.state.get_spatial_metric()
            preferred_dataset_id = self._get_preferred_dataset_id()

            def worker():
                return build_spatial_view_payload(
                    db_path=db_path,
                    polygon_name=polygon_name,
                    observed_at=observed_at,
                    metric=metric,
                    dataset_id=preferred_dataset_id,
                )

            def on_success(payload: dict[str, Any]) -> None:
                self._render_spatial_payload(payload)
                self._record_last_run(
                    action="render-spatial-view",
                    success=True,
                    outputs=[
                        f"dataset={payload['dataset_id']}",
                        f"polygon={payload['polygon_name']}",
                        f"metric={payload['metric']}",
                        f"timestamp={payload['observed_at'].isoformat(timespec='seconds')}",
                    ],
                )
                LOGGER.info(
                    "面ビューを描画しました: polygon=%s metric=%s dataset=%s",
                    payload["polygon_name"],
                    payload["metric"],
                    payload["dataset_id"],
                )

            self._start_background_task(
                action_name="render-spatial-view",
                busy_text="面ビューを描画しています...",
                user_error_message="面ビュー描画に失敗しました。",
                worker=worker,
                on_success=on_success,
            )
        except Exception as exc:
            self._record_last_run(action="render-spatial-view", success=False, error=str(exc))
            self._show_error("面ビュー描画に失敗しました。", detail=str(exc))

    def _handle_init_db(self) -> None:
        """DB 初期化を実行する。"""
        try:
            db_path = self._validate_db_path()
            self._validate_db_path_inline()

            def worker() -> str:
                with open_db(db_path) as conn:
                    initialize_schema(conn)
                return db_path

            def on_success(result: str) -> None:
                self._invalidate_db_related_caches(result)
                self._persist_settings()
                self._load_db_metadata()
                self._record_last_run(action="init-db", success=True, outputs=[result])
                LOGGER.info("DB を初期化しました: %s", result)

            self._start_background_task(
                action_name="init-db",
                busy_text="DB を初期化しています...",
                user_error_message="DB 初期化に失敗しました。",
                worker=worker,
                on_success=on_success,
            )
        except Exception as exc:
            self._show_error("DB 初期化に失敗しました。", detail=str(exc))

    def _handle_ingest(self) -> None:
        """取り込みを実行する。"""
        try:
            db_path = self._validate_db_path()
            input_paths = self._validate_input_paths()
            polygon_dir = self.state.polygon_dir_var.get().strip() or None
            ingest_dataset_id = self.state.ingest_dataset_id_var.get().strip() or None
            self._validate_input_paths_inline()
            if len(input_paths) > 1 and ingest_dataset_id:
                raise ValueError("複数入力のときは取り込みIDを指定できません。")

            def worker() -> list[str]:
                if len(input_paths) == 1:
                    ingest_uc_rainfall(
                        db_path=db_path,
                        input_path=input_paths[0],
                        polygon_dir=polygon_dir,
                        dataset_id=ingest_dataset_id,
                    )
                else:
                    ingest_uc_rainfall_many(
                        db_path=db_path,
                        input_paths=input_paths,
                        polygon_dir=polygon_dir,
                    )
                return input_paths

            def on_success(result: list[str]) -> None:
                self._invalidate_db_related_caches(db_path)
                self._persist_settings()
                self._load_db_metadata()
                self._record_last_run(action="ingest", success=True, outputs=result)
                LOGGER.info("取り込みが完了しました。件数=%s", len(result))

            self._start_background_task(
                action_name="ingest",
                busy_text="取り込みを実行しています...",
                user_error_message="取り込みに失敗しました。",
                worker=worker,
                on_success=on_success,
            )
        except Exception as exc:
            self._show_error("取り込みに失敗しました。", detail=str(exc))

    def _handle_list_candidates(self) -> None:
        """候補セル一覧を更新する。"""
        try:
            db_path = self._validate_db_path()
            polygon_name = self._validate_polygon_name()
            preferred_dataset = self._get_preferred_dataset_id()
            cache_key = (db_path, polygon_name, preferred_dataset)

            def worker():
                cached = self._candidate_frame_cache.get(cache_key)
                if cached is not None:
                    return cached.copy()
                frame = list_candidate_cells(db_path=db_path, dataset_id=preferred_dataset, polygon_name=polygon_name)
                self._candidate_frame_cache[cache_key] = frame.copy()
                return frame

            def on_success(frame) -> None:
                self._populate_candidate_tree(frame)
                self._persist_settings()
                self._record_last_run(action="list-cells", success=True, outputs=[f"候補セル数={len(frame)}"])
                LOGGER.info("候補セル一覧を更新しました。件数=%s", len(frame))
                if frame.empty:
                    self._show_info("候補セルは見つかりませんでした。")

            self._start_background_task(
                action_name="list-cells",
                busy_text="候補セル一覧を更新しています...",
                user_error_message="候補セル一覧更新に失敗しました。",
                worker=worker,
                on_success=on_success,
            )
        except Exception as exc:
            self._show_error("候補セル一覧更新に失敗しました。", detail=str(exc))

    def _handle_plot(self) -> None:
        """イベントグラフを出力する。"""
        try:
            db_path = self._validate_db_path()
            polygon_name = self._validate_polygon_name()
            view_start, view_end = self._validate_plot_times()
            out_dir = self.state.out_dir_var.get().strip()
            if not out_dir:
                raise ValueError("出力先フォルダを指定してください。")
            series_mode = self.state.get_series_mode()
            local_row = None
            local_col = None
            if series_mode == "cell":
                if not self.state.local_row_var.get().strip() or not self.state.local_col_var.get().strip():
                    raise ValueError("セルモードでは流域内行と流域内列を指定してください。")
                local_row = int(self.state.local_row_var.get().strip())
                local_col = int(self.state.local_col_var.get().strip())
            preferred_dataset_id = self._get_preferred_dataset_id()

            def worker():
                return generate_metric_event_charts(
                    db_path=db_path,
                    dataset_id=preferred_dataset_id,
                    polygon_name=polygon_name,
                    row=None,
                    col=None,
                    local_row=local_row,
                    local_col=local_col,
                    series_mode=series_mode,
                    view_start=view_start,
                    view_end=view_end,
                    out_dir=out_dir,
                )

            def on_success(paths) -> None:
                path_strings = [str(path) for path in paths]
                self._persist_settings()
                self._record_last_run(action="plot", success=True, outputs=path_strings)
                LOGGER.info("グラフ出力が完了しました。件数=%s", len(paths))

            self._start_background_task(
                action_name="plot",
                busy_text="グラフを出力しています...",
                user_error_message="グラフ出力に失敗しました。",
                worker=worker,
                on_success=on_success,
            )
        except Exception as exc:
            self._show_error("グラフ出力に失敗しました。", detail=str(exc))

    def _handle_save_test_context(self) -> None:
        """現在状態を JSON として保存する。"""
        try:
            path = self._save_context()
            LOGGER.info("テスト状態を保存しました: %s", path)
        except Exception as exc:
            self._show_error("テスト状態の保存に失敗しました。", detail=str(exc))

    def _handle_save_widget_tree(self) -> None:
        """widget tree を保存する。"""
        try:
            path = self._save_widget_tree()
            LOGGER.info("ウィジェット状態を保存しました: %s", path)
        except Exception as exc:
            self._show_error("ウィジェット状態の保存に失敗しました。", detail=str(exc))

    def _handle_save_screenshot(self) -> None:
        """画面を保存する。"""
        try:
            path = self._save_screenshot()
            if path is None:
                raise RuntimeError("画面保存に失敗しました。")
            LOGGER.info("画面を保存しました: %s", path)
        except Exception as exc:
            self._show_error("画面保存に失敗しました。", detail=str(exc))

    def _handle_save_log(self) -> None:
        """ログをテキストへ保存する。"""
        try:
            path = self._save_log()
            LOGGER.info("ログを保存しました: %s", path)
        except Exception as exc:
            self._show_error("ログ保存に失敗しました。", detail=str(exc))

    def _on_test_mode_toggled(self) -> None:
        """テストモード切替時の処理。"""
        mode = "ON" if self.state.test_mode_var.get() else "OFF"
        LOGGER.info("テストモードを切り替えました: %s", mode)
        self.root.attributes("-topmost", bool(self.state.test_mode_var.get()))
        self._update_test_summary()

    def _poll_action_requests(self) -> None:
        """AI テストモードの操作要求ファイルを監視する。"""
        try:
            if self.state.test_mode_var.get():
                request = load_action_request()
                if request is not None:
                    self._process_action_request(request)
                    clear_action_request()
        except Exception as exc:
            LOGGER.exception("テストモードの操作要求処理に失敗しました: %s", exc)
        finally:
            self.root.after(350, self._poll_action_requests)

    def _process_action_request(self, request: dict[str, Any]) -> None:
        """操作要求を解釈して GUI へ反映する。"""
        request_id = str(request.get("request_id", datetime.now().isoformat()))
        if request_id == self.state.last_processed_request_id:
            return
        self.state.last_processed_request_id = request_id
        actions = request.get("actions")
        if not isinstance(actions, list):
            actions = [request]
        results: list[dict[str, Any]] = []
        for action in actions:
            result = self._execute_action(action)
            results.append(result)
            if not result["success"]:
                break
        screenshot_path = self._save_screenshot()
        context_path = self._save_context()
        widget_tree_path = self._save_widget_tree()
        self._save_log()
        save_action_result(
            {
                "request_id": request_id,
                "processed_at": datetime.now(),
                "results": results,
                "context_path": str(context_path),
                "widget_tree_path": str(widget_tree_path),
                "screenshot_path": str(screenshot_path) if screenshot_path else None,
            }
        )

    def _execute_action(self, action: dict[str, Any]) -> dict[str, Any]:
        """単一アクションを実行する。"""
        widget_id = str(action.get("widget_id", "")).strip()
        action_name = str(action.get("action", "")).strip()
        if not action_name:
            return {"success": False, "error": "action が必要です。"}
        if action_name == "wait_until_idle":
            try:
                timeout_ms = int(action.get("timeout_ms", 10000))
                self._wait_until_idle(timeout_ms=timeout_ms)
                LOGGER.info("テストモード操作: action=%s timeout_ms=%s", action_name, timeout_ms)
                return {"success": True, "widget_id": widget_id or "window.root", "action": action_name}
            except Exception as exc:
                LOGGER.error("テストモード操作に失敗しました: action=%s detail=%s", action_name, exc)
                return {"success": False, "widget_id": widget_id or "window.root", "action": action_name, "error": str(exc)}

        if not widget_id:
            return {"success": False, "error": "widget_id と action が必要です。"}
        info = self.state.widget_registry.get(widget_id)
        if info is None:
            return {"success": False, "error": f"未知の widget_id です: {widget_id}"}
        widget = info["widget"]
        try:
            if action_name in {"click", "invoke"}:
                if not hasattr(widget, "invoke"):
                    raise ValueError(f"invoke 非対応 widget です: {widget_id}")
                widget.invoke()
            elif action_name == "render_spatial_view":
                self._handle_render_spatial_view()
            elif action_name in {"set_text", "select"}:
                self._set_widget_value(widget, action.get("value", ""))
            elif action_name == "focus":
                widget.focus_force()
            elif action_name == "select_tree_row":
                self._select_tree_row(widget, action)
            elif action_name == "click_canvas_point":
                self._execute_canvas_point_action(widget, action)
            else:
                raise ValueError(f"未知の操作種別です: {action_name}")
            self.root.update()
            LOGGER.info("テストモード操作: action=%s widget_id=%s", action_name, widget_id)
            return {"success": True, "widget_id": widget_id, "action": action_name}
        except Exception as exc:
            LOGGER.error("テストモード操作に失敗しました: action=%s widget_id=%s detail=%s", action_name, widget_id, exc)
            return {"success": False, "widget_id": widget_id, "action": action_name, "error": str(exc)}

    def _wait_until_idle(self, *, timeout_ms: int) -> None:
        """バックグラウンド処理完了まで待つ。"""
        deadline = datetime.now().timestamp() + timeout_ms / 1000.0
        while self._busy_action is not None:
            self.root.update()
            if datetime.now().timestamp() > deadline:
                raise TimeoutError(f"タイムアウトしました: busy_action={self._busy_action}")

    def _set_widget_value(self, widget: tk.Widget, value: Any) -> None:
        """Entry / Text / Combobox / Checkbutton へ値を設定する。"""
        if isinstance(widget, tk.Text):
            self._set_text_widget(widget, str(value))
            self._refresh_control_states()
            return
        if isinstance(widget, tk.Listbox):
            items = value if isinstance(value, list) else [str(value)]
            self._set_listbox_items(widget, [str(item) for item in items])
            self._refresh_control_states()
            self._validate_input_paths_inline()
            return
        if isinstance(widget, ttk.Combobox):
            widget.set(str(value))
            self._refresh_control_states()
            if widget is self.polygon_name_combo:
                self._on_polygon_name_changed()
            if widget is self.spatial_metric_combo:
                self._update_test_summary()
            return
        if isinstance(widget, ttk.Entry):
            widget.delete(0, "end")
            widget.insert(0, str(value))
            self._refresh_control_states()
            if widget is self.db_entry:
                self._on_db_path_changed()
            elif widget is self.out_dir_entry:
                self._validate_out_dir_inline()
            elif widget is self.view_start_entry or widget is self.view_end_entry:
                self._validate_datetime_inputs_inline()
            elif widget is self.spatial_timestamp_entry:
                self._validate_spatial_timestamp_inline()
            return
        if widget is self.test_mode_check:
            self.state.test_mode_var.set(bool(value))
            self._on_test_mode_toggled()
            return
        raise ValueError(f"値設定に対応していない widget です: {widget!r}")

    def _select_tree_row(self, widget: tk.Widget, action: dict[str, Any]) -> None:
        """Treeview で行選択を行う。"""
        if not isinstance(widget, ttk.Treeview):
            raise ValueError("select_tree_row は Treeview 専用です。")
        row_index = action.get("row_index")
        criteria = action.get("criteria")
        target_item: str | None = None
        if isinstance(row_index, int):
            items = widget.get_children()
            if row_index < 0 or row_index >= len(items):
                raise ValueError(f"row_index が範囲外です: {row_index}")
            target_item = items[row_index]
        elif isinstance(criteria, dict):
            for item_id in widget.get_children():
                row = self._candidate_items.get(item_id, {})
                if all(str(row.get(key)) == str(value) for key, value in criteria.items()):
                    target_item = item_id
                    break
            if target_item is None:
                raise ValueError("指定条件に一致する行が見つかりません。")
        else:
            raise ValueError("row_index または criteria が必要です。")
        widget.selection_set(target_item)
        widget.focus(target_item)
        self._on_candidate_selected()

    def _execute_canvas_point_action(self, widget: tk.Widget, action: dict[str, Any]) -> None:
        """面ビュー canvas に対するテスト用セル選択操作を行う。"""
        if widget is not self.spatial_canvas.get_tk_widget():
            raise ValueError("click_canvas_point は面ビュー canvas 専用です。")
        if self._spatial_payload is None:
            raise ValueError("面ビューがまだ描画されていません。")
        if "polygon_local_row" in action and "polygon_local_col" in action:
            self._apply_spatial_selected_cell(int(action["polygon_local_row"]), int(action["polygon_local_col"]))
            return
        if "xdata" in action and "ydata" in action:
            xdata = float(action["xdata"])
            ydata = float(action["ydata"])
            for _, info in self._spatial_rectangles:
                if (
                    float(info["minx"]) <= xdata <= float(info["maxx"])
                    and float(info["miny"]) <= ydata <= float(info["maxy"])
                ):
                    self._apply_spatial_selected_cell(
                        int(info["polygon_local_row"]),
                        int(info["polygon_local_col"]),
                    )
                    return
            raise ValueError("指定座標に一致するセルが見つかりません。")
        raise ValueError("polygon_local_row/local_col または xdata/ydata が必要です。")

    def _is_widget_enabled(self, widget: tk.Widget) -> bool:
        """widget の有効状態を返す。"""
        try:
            state = str(widget.cget("state"))
        except tk.TclError:
            return True
        return state not in {"disabled", str(tk.DISABLED)}

    def _get_widget_value(self, widget: tk.Widget) -> Any:
        """widget 現在値を機械可読な形で返す。"""
        if isinstance(widget, tk.Text):
            return widget.get("1.0", "end-1c")
        if isinstance(widget, tk.Listbox):
            return {
                "items": [str(widget.get(index)) for index in range(widget.size())],
                "selected_indices": list(widget.curselection()),
            }
        if isinstance(widget, ttk.Treeview):
            return {"row_count": len(widget.get_children()), "selected": list(widget.selection())}
        if isinstance(widget, ttk.Combobox):
            return str(widget.get())
        if isinstance(widget, ttk.Entry):
            return str(widget.get())
        try:
            return str(widget.cget("text"))
        except tk.TclError:
            return None

    def _on_close(self) -> None:
        """終了時に設定とテストアーティファクトを保存する。"""
        try:
            self._persist_settings()
            self._save_log()
        finally:
            if self._log_handler is not None:
                logging.getLogger().removeHandler(self._log_handler)
            self.root.destroy()


def run_gui(*, test_mode: bool = False) -> None:
    """GUI を起動する。"""
    app = UcRainfallGuiApp(test_mode=test_mode)
    app.run()


def main() -> None:
    """モジュール実行用のエントリポイント。"""
    parser = argparse.ArgumentParser(description="UC降雨処理 GUI")
    parser.add_argument("--test-mode", action="store_true", help="AI テストモードで起動する")
    args = parser.parse_args()
    run_gui(test_mode=args.test_mode)


if __name__ == "__main__":
    main()
