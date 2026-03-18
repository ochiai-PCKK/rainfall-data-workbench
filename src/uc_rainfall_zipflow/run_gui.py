from __future__ import annotations

import json
import threading
import tkinter as tk
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import cast

from .application import run_zipflow
from .errors import ZipFlowError
from .graph_builder import build_reference_output_paths
from .models import RunConfig
from .regions import load_region_specs
from .style_profile import default_style_profile_path
from .style_tuner_gui import launch_style_tuner

_DATE_FMT = "%Y-%m-%d"
_GUI_STATE_PATH = Path("config/uc_rainfall_zipflow/gui_state.json")
_SCREENSHOT_DIR = Path("outputs/_gui_screenshots")
_RUN_MODES = ("解析雨量データ", "Excelデータ")

_REGION_LABELS = {
    "nishiyoke": "西除川",
    "higashiyoke": "東除川",
    "nishiyoke_higashiyoke": "西除川+東除川",
    "yamatogawa": "大和川",
}
_OUTPUT_LABELS = {
    "raster": "流域クリップラスタ",
    "raster_bbox": "BBoxラスタ",
    "plots_ref": "整形時系列グラフ",
    "timeseries_csv": "分析CSVセット",
}
_GRAPH_KIND_LABELS = {
    "sum": "重み付き合計",
    "mean": "流域平均",
}


def _parse_date(raw: str, *, field_name: str) -> date:
    try:
        return datetime.strptime(raw.strip(), _DATE_FMT).date()
    except ValueError as exc:
        raise ValueError(f"{field_name} は YYYY-MM-DD 形式で入力してください。") from exc


def _resolve_base_date(start_date: date, end_date: date) -> date:
    day_count = (end_date - start_date).days + 1
    return start_date + timedelta(days=day_count // 2)


def _list_available_region_keys(polygon_dir: Path) -> set[str]:
    try:
        specs = load_region_specs(polygon_dir)
    except Exception:
        return set()
    return {spec.region_key for spec in specs}


def _load_state() -> dict[str, object]:
    if not _GUI_STATE_PATH.exists():
        return {}
    try:
        raw = json.loads(_GUI_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _save_state(state: dict[str, object]) -> None:
    _GUI_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _GUI_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _find_latest_timeseries_csv(*, output_root: Path, region_key: str) -> Path | None:
    if not output_root.exists():
        return None
    pattern = f"*/analysis_csv/{region_key}/{region_key}_*_timeseries.csv"
    candidates = [p for p in output_root.glob(pattern) if p.is_file()]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


class ZipFlowGui:
    def __init__(
        self,
        *,
        auto_capture_seconds: float | None = None,
        auto_exit_after_capture: bool = False,
    ) -> None:
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("流域雨量グラフ作成（メインウィンドウ）")
        self.root.minsize(980, 680)

        self._state = _load_state()
        self._is_running = False
        self._last_result: dict[str, object] | None = None
        self._path_rows: list[tuple[ttk.Frame, ttk.Label, ttk.Button]] = []
        self._tuner_csv_manual = False
        self._last_auto_tuner_csv = ""
        self._auto_capture_seconds = auto_capture_seconds
        self._auto_exit_after_capture = auto_exit_after_capture
        self._status_default_style = "StatusDefault.TLabel"
        self._status_error_style = "StatusError.TLabel"

        self._build_vars()
        self._build_layout()
        self._adjust_layout_for_content()
        self._place_window_initial()
        self.root.deiconify()
        self._apply_loaded_state()
        self._refresh_region_choices()
        self._update_graph_span_label()
        self._set_auto_tuner_csv()
        self._bind_auto_csv_refresh()
        self.root.bind("<Control-Shift-S>", self._on_capture_shortcut)
        self.root.bind("<F12>", self._on_capture_shortcut)
        self._append_log("画面を初期化しました。")
        if self._auto_capture_seconds is not None and self._auto_capture_seconds >= 0.0:
            delay_ms = int(self._auto_capture_seconds * 1000)
            self.root.after(delay_ms, self._auto_capture_once)

    def _place_window_initial(self) -> None:
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        current_w = max(980, self.root.winfo_reqwidth())
        current_h = max(680, self.root.winfo_reqheight())
        width = min(current_w, max(960, screen_w - 120))
        height = min(current_h, max(660, screen_h - 140))
        x = max(24, (screen_w - width) // 2)
        y = max(24, (screen_h - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _adjust_layout_for_content(self) -> None:
        self.root.update_idletasks()
        root_children = self.root.winfo_children()
        if not root_children:
            return
        root_pad = root_children[0]
        frames = [child for child in root_pad.winfo_children() if isinstance(child, ttk.Frame)]
        if len(frames) < 2:
            return
        body = frames[1]
        panels = body.winfo_children()
        if len(panels) < 2:
            return
        left_req = max(520, int(panels[0].winfo_reqwidth()) + 24)
        right_req = max(620, int(panels[1].winfo_reqwidth()))
        body.columnconfigure(0, minsize=left_req)
        body.columnconfigure(1, minsize=right_req)
        self._normalize_path_rows()

    def _normalize_path_rows(self) -> None:
        if not self._path_rows:
            return
        self.root.update_idletasks()
        max_label = max(lbl.winfo_reqwidth() for _, lbl, _ in self._path_rows)
        max_button = max(btn.winfo_reqwidth() for _, _, btn in self._path_rows)
        for row, _lbl, _btn in self._path_rows:
            row.columnconfigure(0, minsize=max_label + 8)
            row.columnconfigure(2, minsize=max_button + 4)

    def _build_vars(self) -> None:
        today = date.today()
        self.start_date_var = tk.StringVar(value=(today - timedelta(days=2)).strftime(_DATE_FMT))
        self.end_date_var = tk.StringVar(value=today.strftime(_DATE_FMT))
        self.run_mode_var = tk.StringVar(value="解析雨量データ")
        self.input_zipdir_var = tk.StringVar(value=r"outputs\uc_download\downloads")
        self.input_excel_var = tk.StringVar(value="")
        self.output_dir_var = tk.StringVar(value=r"outputs\uc_rainfall_zipflow")
        self.polygon_dir_var = tk.StringVar(value=r"data\大阪狭山市_流域界")
        self.enable_log_var = tk.BooleanVar(value=False)
        self.export_svg_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="待機中")
        self.updated_var = tk.StringVar(value="最終更新: --")
        self.graph_span_var = tk.StringVar(value="自動判定: 3日")
        self.tuner_csv_var = tk.StringVar(value="")
        self.tuner_help_var = tk.StringVar(
            value="自動選択: 流域最新 -> 直近実行 -> 手動選択（CSV未指定時は疑似データで起動）"
        )

        self.region_vars = {k: tk.BooleanVar(value=(k == "nishiyoke_higashiyoke")) for k in _REGION_LABELS}
        self.output_vars = {
            "raster": tk.BooleanVar(value=True),
            "raster_bbox": tk.BooleanVar(value=True),
            "plots_ref": tk.BooleanVar(value=True),
            "timeseries_csv": tk.BooleanVar(value=False),
        }
        self.graph_kind_vars = {
            "sum": tk.BooleanVar(value=True),
            "mean": tk.BooleanVar(value=True),
        }

    def _bind_auto_csv_refresh(self) -> None:
        self.output_dir_var.trace_add("write", lambda *_: self._refresh_tuner_csv_if_needed())
        for var in self.region_vars.values():
            var.trace_add("write", lambda *_: self._refresh_tuner_csv_if_needed())

    def _refresh_tuner_csv_if_needed(self) -> None:
        current = self.tuner_csv_var.get().strip()
        if self._tuner_csv_manual:
            if current and Path(current).exists():
                return
            self._tuner_csv_manual = False
            self._append_log("手動指定CSVが見つからないため自動探索へ切替します。")
        elif current and current != self._last_auto_tuner_csv and Path(current).exists():
            self._tuner_csv_manual = True
            return
        self._set_auto_tuner_csv()

    def _build_layout(self) -> None:
        style = ttk.Style(self.root)
        style.configure(self._status_default_style, foreground="#111111")
        style.configure(self._status_error_style, foreground="#C00000")

        root_pad = ttk.Frame(self.root, padding=8)
        root_pad.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(root_pad)
        header.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(header, text="流域雨量グラフ作成", font=("", 16, "bold")).pack(side=tk.LEFT)
        chip_wrap = ttk.Frame(header)
        chip_wrap.pack(side=tk.RIGHT)
        ttk.Label(chip_wrap, text="既定流域: 西除川+東除川", padding=(10, 4)).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Label(chip_wrap, text="時刻基準: JST", padding=(10, 4)).pack(side=tk.LEFT)

        body = ttk.Frame(root_pad)
        body.pack(fill=tk.BOTH, expand=True)
        body.columnconfigure(0, weight=4, minsize=0)
        body.columnconfigure(1, weight=6, minsize=0)
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.rowconfigure(0, weight=1)
        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)

        self._build_mode_group(left)
        self._build_input_group(left)
        self._build_standard_group(left)
        self._build_action_group(left)
        self._build_output_list_group(left)

        self._build_right_pane(right)

        status_bar = ttk.Frame(root_pad, padding=(8, 6))
        status_bar.pack(fill=tk.X, pady=(8, 0))
        self.status_label = ttk.Label(status_bar, textvariable=self.status_var, style=self._status_default_style)
        self.status_label.pack(side=tk.LEFT)
        ttk.Label(status_bar, textvariable=self.updated_var).pack(side=tk.LEFT, padx=(14, 0))

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_mode_group(self, parent: ttk.Frame) -> None:
        frm = ttk.LabelFrame(parent, text="モード", padding=10)
        frm.pack(fill=tk.X, pady=(0, 8))
        row = ttk.Frame(frm)
        row.pack(fill=tk.X)
        for mode in _RUN_MODES:
            ttk.Radiobutton(
                row,
                text=mode,
                value=mode,
                variable=self.run_mode_var,
                command=self._update_input_mode_visibility,
            ).pack(side=tk.LEFT, padx=(0, 12))

    def _build_input_group(self, parent: ttk.Frame) -> None:
        frm = ttk.LabelFrame(parent, text="入出力", padding=10)
        frm.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(frm, text="期間指定（必須）").pack(anchor=tk.W, pady=(0, 2))
        period_row = ttk.Frame(frm)
        period_row.pack(fill=tk.X, pady=(2, 3))
        ttk.Entry(period_row, textvariable=self.start_date_var, width=15).pack(side=tk.LEFT)
        ttk.Label(period_row, text="〜", padding=(6, 0)).pack(side=tk.LEFT)
        ttk.Entry(period_row, textvariable=self.end_date_var, width=15).pack(side=tk.LEFT)
        ttk.Label(frm, text="制約: 期間差は3日または5日のみ").pack(anchor=tk.W, pady=(0, 6))

        self.start_date_var.trace_add("write", lambda *_: self._update_graph_span_label())
        self.end_date_var.trace_add("write", lambda *_: self._update_graph_span_label())

        self.input_zip_row = self._path_row(frm, "入力ZIPディレクトリ", self.input_zipdir_var, ask_dir=True)
        self.input_excel_row = self._path_row(
            frm,
            "入力Excelファイル",
            self.input_excel_var,
            ask_file=True,
            filetypes=[("Excel", "*.xlsx;*.xls"), ("すべて", "*.*")],
        )
        self.output_dir_row = self._path_row(frm, "出力ディレクトリ", self.output_dir_var, ask_dir=True)
        self._path_row(
            frm,
            "ポリゴンディレクトリ",
            self.polygon_dir_var,
            ask_dir=True,
            on_change=self._refresh_region_choices,
        )
        ttk.Checkbutton(frm, text="ログを保存する", variable=self.enable_log_var).pack(anchor=tk.W, pady=(6, 0))
        self._update_input_mode_visibility()

    def _build_standard_group(self, parent: ttk.Frame) -> None:
        frm = ttk.LabelFrame(parent, text="実行設定", padding=10)
        frm.pack(fill=tk.X, pady=(0, 8))
        def row_block(label: str) -> tuple[ttk.Frame, ttk.Frame]:
            row = ttk.Frame(frm)
            row.pack(fill=tk.X, pady=(2, 4))
            ttk.Label(row, text=label, width=9).pack(side=tk.LEFT, anchor=tk.N)
            body = ttk.Frame(row)
            body.pack(side=tk.LEFT, fill=tk.X, expand=True)
            return row, body

        _row1, region_wrap = row_block("対象流域")
        for key in _REGION_LABELS:
            ttk.Checkbutton(region_wrap, text=_REGION_LABELS[key], variable=self.region_vars[key]).pack(
                side=tk.LEFT,
                padx=(0, 10),
            )

        _row2, out_wrap = row_block("出力種別")
        for key in _OUTPUT_LABELS:
            ttk.Checkbutton(out_wrap, text=_OUTPUT_LABELS[key], variable=self.output_vars[key]).pack(
                side=tk.LEFT,
                padx=(0, 10),
            )

        _row3, kind_wrap = row_block("グラフ指標")
        for key in _GRAPH_KIND_LABELS:
            ttk.Checkbutton(kind_wrap, text=_GRAPH_KIND_LABELS[key], variable=self.graph_kind_vars[key]).pack(
                side=tk.LEFT,
                padx=(0, 10),
            )
        ttk.Checkbutton(kind_wrap, text="SVGも出力", variable=self.export_svg_var).pack(side=tk.LEFT, padx=(0, 2))

    def _build_action_group(self, parent: ttk.Frame) -> None:
        row = ttk.Frame(parent, padding=(0, 2))
        row.pack(fill=tk.X, pady=(2, 0))
        self.run_button = ttk.Button(row, text="処理を実行", command=self._on_run_clicked)
        self.run_button.pack(anchor=tk.W)

    def _build_output_list_group(self, parent: ttk.Frame) -> None:
        frm = ttk.LabelFrame(parent, text="出力一覧", padding=10)
        frm.pack(fill=tk.X, pady=(6, 8))
        self.summary_text = tk.Text(frm, height=7, wrap=tk.WORD, font=("", 10))
        self.summary_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        summary_scroll = ttk.Scrollbar(frm, orient=tk.VERTICAL, command=self.summary_text.yview)
        summary_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.summary_text.configure(yscrollcommand=summary_scroll.set)

    def _build_right_pane(self, parent: ttk.Frame) -> None:
        pane = ttk.Frame(parent)
        pane.grid(row=1, column=0, sticky="nsew", pady=(0, 2))
        pane.rowconfigure(0, weight=1, minsize=420)
        pane.rowconfigure(1, weight=0, minsize=0)
        pane.columnconfigure(0, weight=1)

        upper = ttk.LabelFrame(pane, text="実行ログ", padding=10)
        upper.grid(row=0, column=0, sticky="nsew", pady=(4, 8))
        upper.columnconfigure(0, weight=1)
        upper.rowconfigure(1, weight=1)
        self.log_text = tk.Text(upper, height=18, wrap=tk.WORD, font=("", 10))
        self.log_text.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        log_scroll = ttk.Scrollbar(upper, orient=tk.VERTICAL, command=self.log_text.yview)
        log_scroll.grid(row=1, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)

        lower = ttk.Frame(pane)
        lower.grid(row=1, column=0, sticky="nsew")
        lower.columnconfigure(0, weight=1)
        lower.rowconfigure(0, weight=0, minsize=0)

        tuner = ttk.LabelFrame(lower, text="グラフスタイル調整", padding=10)
        tuner.grid(row=0, column=0, columnspan=2, sticky="nsew")
        ttk.Label(tuner, text="対象CSVの使い方", font=("", 9, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(tuner, text="1. 対象CSVを指定すると、そのCSVでプレビューします。").grid(
            row=1,
            column=0,
            columnspan=3,
            sticky="w",
        )
        ttk.Label(
            tuner,
            text="2. 対象CSVを空欄にすると、選択中流域の時系列CSV（*_timeseries.csv）を自動で探して使います。",
        ).grid(row=2, column=0, columnspan=3, sticky="w")
        ttk.Label(tuner, text="3. 自動で見つからない場合は、テンプレートデータでプレビューします。").grid(
            row=3,
            column=0,
            columnspan=3,
            sticky="w",
        )
        ttk.Label(tuner, text="4. 調整後に「保存して閉じる」を押すと、次回のグラフ出力に反映されます。").grid(
            row=4,
            column=0,
            columnspan=3,
            sticky="w",
        )
        tuner_row = ttk.Frame(tuner)
        tuner_row.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        tuner_row.columnconfigure(1, weight=1)
        label_csv = ttk.Label(tuner_row, text="対象CSV")
        label_csv.grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Entry(tuner_row, textvariable=self.tuner_csv_var).grid(row=0, column=1, sticky="ew", padx=(0, 4))
        button_csv = ttk.Button(tuner_row, text="選択", command=self._on_pick_tuner_csv, width=5)
        button_csv.grid(row=0, column=2, sticky="e")
        self._path_rows.append((tuner_row, label_csv, button_csv))
        # 自動選択補助文は簡素化方針により表示しない

        btns = ttk.Frame(lower)
        btns.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Button(btns, text="グラフスタイル調整", command=self._on_open_style_tuner).pack(side=tk.LEFT)
        ttk.Label(btns, text="保存して閉じると次回実行で反映されます").pack(side=tk.LEFT, padx=(8, 0))

    def _path_row(
        self,
        parent: tk.Misc,
        label: str,
        var: tk.StringVar,
        *,
        ask_dir: bool = False,
        ask_file: bool = False,
        filetypes: list[tuple[str, str]] | None = None,
        on_change=None,
    ) -> ttk.Frame:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=2)
        row.columnconfigure(1, weight=1)
        label_widget = ttk.Label(row, text=label)
        label_widget.grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Entry(row, textvariable=var).grid(row=0, column=1, sticky="ew", padx=(0, 4))

        def choose() -> None:
            initial = var.get().strip() or "."
            selected = None
            if ask_dir:
                selected = filedialog.askdirectory(initialdir=initial, title=label)
            elif ask_file:
                selected = filedialog.askopenfilename(
                    initialdir=str(Path(initial).parent if Path(initial).suffix else Path(initial)),
                    title=label,
                    filetypes=filetypes if filetypes is not None else [("JSON", "*.json"), ("すべて", "*.*")],
                )
            if selected:
                var.set(selected)
                if on_change is not None:
                    on_change()

        button_widget = ttk.Button(row, text="参照", command=choose, width=5)
        button_widget.grid(row=0, column=2, sticky="e")
        self._path_rows.append((row, label_widget, button_widget))
        if on_change is not None:
            var.trace_add("write", lambda *_: on_change())
        return row

    def _update_input_mode_visibility(self) -> None:
        mode = self.run_mode_var.get()
        if mode == "Excelデータ":
            self.input_zip_row.pack_forget()
            self.input_excel_row.pack(fill=tk.X, pady=2, before=self.output_dir_row)
        else:
            self.input_excel_row.pack_forget()
            self.input_zip_row.pack(fill=tk.X, pady=2, before=self.output_dir_row)

    def _append_log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"{stamp}  {message}\n")
        self.log_text.see(tk.END)
        self.updated_var.set(f"最終更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    def _set_status(self, text: str, *, is_error: bool = False) -> None:
        self.status_var.set(text)
        if is_error:
            self.status_label.configure(style=self._status_error_style)
        else:
            self.status_label.configure(style=self._status_default_style)

    def _set_summary(self, text: str) -> None:
        self.summary_text.delete("1.0", tk.END)
        self.summary_text.insert("1.0", text)

    def _update_graph_span_label(self) -> None:
        try:
            start = _parse_date(self.start_date_var.get(), field_name="開始日")
            end = _parse_date(self.end_date_var.get(), field_name="終了日")
            day_count = (end - start).days + 1
            if day_count in (3, 5):
                self.graph_span_var.set(f"自動判定: {day_count}日")
                self.run_button.configure(state=tk.NORMAL)
                if self.status_var.get().startswith("期間エラー"):
                    self._set_status("待機中")
            else:
                self.graph_span_var.set("自動判定: 期間エラー（3日 or 5日）")
                self.run_button.configure(state=tk.DISABLED)
                self._set_status("期間エラー（3日 or 5日）", is_error=True)
        except ValueError:
            self.graph_span_var.set("自動判定: 日付形式エラー")
            self.run_button.configure(state=tk.DISABLED)
            self._set_status("期間エラー（3日 or 5日）", is_error=True)

    def _refresh_region_choices(self) -> None:
        keys = _list_available_region_keys(Path(self.polygon_dir_var.get().strip() or "."))
        for key, var in self.region_vars.items():
            if key not in keys:
                var.set(False)

    def _on_save_state_clicked(self) -> None:
        state = self._collect_state_payload()
        _save_state(state)
        self._append_log(f"設定を保存しました: {_GUI_STATE_PATH}")
        self._set_status("設定保存完了")

    def _on_reload_state_clicked(self) -> None:
        self._state = _load_state()
        self._apply_loaded_state()
        self._append_log("設定を再読込しました。")
        self._set_status("設定読込完了")

    def _collect_state_payload(self) -> dict[str, object]:
        return {
            "run_mode": self.run_mode_var.get().strip(),
            "input_zipdir": self.input_zipdir_var.get().strip(),
            "input_excel": self.input_excel_var.get().strip(),
            "output_dir": self.output_dir_var.get().strip(),
            "polygon_dir": self.polygon_dir_var.get().strip(),
            "period_start": self.start_date_var.get().strip(),
            "period_end": self.end_date_var.get().strip(),
            "selected_regions": [k for k, v in self.region_vars.items() if v.get()],
            "selected_outputs": [k for k, v in self.output_vars.items() if v.get()],
            "ref_graph_kinds": [k for k, v in self.graph_kind_vars.items() if v.get()],
            "enable_log": bool(self.enable_log_var.get()),
            "export_svg": bool(self.export_svg_var.get()),
        }

    def _apply_loaded_state(self) -> None:
        state = self._state
        mode = str(state.get("run_mode", self.run_mode_var.get()))
        self.run_mode_var.set(mode if mode in _RUN_MODES else _RUN_MODES[0])
        self.input_zipdir_var.set(str(state.get("input_zipdir", self.input_zipdir_var.get())))
        self.input_excel_var.set(str(state.get("input_excel", self.input_excel_var.get())))
        self.output_dir_var.set(str(state.get("output_dir", self.output_dir_var.get())))
        self.polygon_dir_var.set(str(state.get("polygon_dir", self.polygon_dir_var.get())))
        self.start_date_var.set(str(state.get("period_start", self.start_date_var.get())))
        self.end_date_var.set(str(state.get("period_end", self.end_date_var.get())))
        self.enable_log_var.set(bool(state.get("enable_log", self.enable_log_var.get())))
        self.export_svg_var.set(bool(state.get("export_svg", self.export_svg_var.get())))

        selected_regions = set(cast(list[str], state.get("selected_regions", [])))
        if selected_regions:
            for key, var in self.region_vars.items():
                var.set(key in selected_regions)
        selected_outputs = set(cast(list[str], state.get("selected_outputs", [])))
        if selected_outputs:
            for key, var in self.output_vars.items():
                var.set(key in selected_outputs)
        graph_kinds = set(cast(list[str], state.get("ref_graph_kinds", [])))
        if graph_kinds:
            for key, var in self.graph_kind_vars.items():
                var.set(key in graph_kinds)
        self._update_input_mode_visibility()

    def _validate_for_run(self) -> tuple[RunConfig, int]:
        mode = self.run_mode_var.get().strip()
        if mode == "Excelデータ":
            excel_path = self.input_excel_var.get().strip()
            if not excel_path:
                raise ValueError("Excelモードでは入力Excelファイルを指定してください。")
            if not Path(excel_path).exists():
                raise ValueError(f"入力Excelファイルが見つかりません: {excel_path}")
            raise ValueError("Excelデータモードは現在準備中です。解析雨量データモードを使用してください。")

        start = _parse_date(self.start_date_var.get(), field_name="開始日")
        end = _parse_date(self.end_date_var.get(), field_name="終了日")
        if end < start:
            raise ValueError("終了日は開始日以降にしてください。")
        day_count = (end - start).days + 1
        if day_count not in (3, 5):
            raise ValueError("期間は 3日 または 5日で指定してください。")

        region_keys = tuple(k for k, v in self.region_vars.items() if v.get())
        if not region_keys:
            raise ValueError("対象流域を1つ以上選択してください。")
        output_kinds = tuple(k for k, v in self.output_vars.items() if v.get())
        if not output_kinds:
            raise ValueError("出力種別を1つ以上選択してください。")
        graph_kinds = tuple(k for k, v in self.graph_kind_vars.items() if v.get())
        if not graph_kinds:
            raise ValueError("グラフ指標を1つ以上選択してください。")

        default_style_path = default_style_profile_path()
        style_path = default_style_path if default_style_path.exists() else None

        config = RunConfig(
            base_date=_resolve_base_date(start, end),
            input_zipdir=Path(self.input_zipdir_var.get().strip()),
            output_root=Path(self.output_dir_var.get().strip()),
            polygon_dir=Path(self.polygon_dir_var.get().strip()),
            enable_log=bool(self.enable_log_var.get()),
            export_svg=bool(self.export_svg_var.get()),
            window_mode="range",
            days_before=0,
            days_after=0,
            start_date=start,
            end_date=end,
            graph_spans=("3d",) if day_count == 3 else ("5d",),
            ref_graph_kinds=graph_kinds,
            style_profile_path=style_path,
            region_keys=region_keys,
            output_kinds=output_kinds,
            on_conflict="rename",
        )
        return config, day_count

    def _resolve_conflict_policy_for_plot_ref(self, config: RunConfig) -> str | None:
        if "plots_ref" not in config.output_kinds:
            return config.on_conflict
        expected = build_reference_output_paths(
            output_dir=config.output_root / "plots_reference",
            region_keys=config.region_keys,
            base_date=config.base_date,
            graph_spans=config.graph_spans,
            ref_graph_kinds=config.ref_graph_kinds,
            export_svg=config.export_svg,
        )
        conflicts = [p for p in expected if p.exists()]
        if not conflicts:
            return config.on_conflict

        preview = "\n".join(str(p) for p in conflicts[:6])
        if len(conflicts) > 6:
            preview += f"\n... 他 {len(conflicts) - 6} 件"
        action = messagebox.askyesnocancel(
            "出力先の重複確認",
            "既存のグラフファイルが見つかりました。\n"
            "はい: 上書き\n"
            "いいえ: 別名保存(_v2, _v3...)\n"
            "キャンセル: 実行中止\n\n"
            f"重複候補:\n{preview}",
        )
        if action is None:
            return None
        if action is True:
            return "overwrite"
        return "rename"

    def _on_run_clicked(self) -> None:
        if self._is_running:
            return
        try:
            config, day_count = self._validate_for_run()
        except ValueError as exc:
            messagebox.showerror("入力エラー", str(exc))
            return
        policy = self._resolve_conflict_policy_for_plot_ref(config)
        if policy is None:
            self._append_log("実行をキャンセルしました（出力ファイル重複）。")
            self._set_status("待機中")
            return
        config = replace(config, on_conflict=policy)
        if "plots_ref" in config.output_kinds:
            self._append_log(f"ファイル衝突時の挙動: {policy}")

        self._is_running = True
        self._set_status("実行中")
        self._append_log(
            f"実行開始: period={config.start_date:%Y-%m-%d}..{config.end_date:%Y-%m-%d} ({day_count}日) "
            f"regions={list(config.region_keys)} outputs={list(config.output_kinds)}"
        )
        _save_state(self._collect_state_payload())

        def worker() -> None:
            result: dict[str, object] | None = None
            error_text: str | None = None
            try:
                result = run_zipflow(config)
            except ZipFlowError as exc:
                error_text = f"[ERROR] {exc}"
            except Exception as exc:  # noqa: BLE001
                error_text = f"[ERROR] 想定外エラー: {exc}"

            def done() -> None:
                self._is_running = False
                if error_text is not None:
                    self._set_status("失敗", is_error=True)
                    self._append_log(error_text)
                    messagebox.showerror("実行失敗", error_text)
                    return
                assert result is not None
                self._last_result = result
                self._set_status("完了")
                self._append_log("実行完了")
                self._set_summary(self._format_summary(result))
                self._set_auto_tuner_csv()

            self.root.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def _format_summary(self, result: dict[str, object]) -> str:
        lines = [
            f"出力先: {result.get('base_dir')}",
            f"採用ZIP数: {result.get('zip_count')}",
            f"グラフ出力数: {result.get('plot_count')}",
            f"時系列CSV数: {result.get('csv_count')} / セルCSV数: {result.get('cell_csv_count')}",
        ]
        if result.get("log_path"):
            lines.append(f"ログ: {result['log_path']}")
        if result.get("csv_readme_path"):
            lines.append(f"CSV説明: {result['csv_readme_path']}")
        return "\n".join(lines)

    def _on_pick_tuner_csv(self) -> None:
        selected = filedialog.askopenfilename(
            title="対象CSVを選択",
            filetypes=[("Timeseries CSV", "*_timeseries.csv"), ("CSV", "*.csv"), ("すべて", "*.*")],
        )
        if selected:
            self.tuner_csv_var.set(selected)
            self._tuner_csv_manual = True
            self._append_log(f"対象CSVを選択しました: {selected}")

    def _resolve_current_graph_span(self) -> str:
        try:
            start = _parse_date(self.start_date_var.get(), field_name="開始日")
            end = _parse_date(self.end_date_var.get(), field_name="終了日")
        except ValueError:
            return "5d"
        day_count = (end - start).days + 1
        return "3d" if day_count == 3 else "5d"

    def _resolve_primary_value_kind(self) -> str:
        if self.graph_kind_vars["mean"].get():
            return "mean"
        return "sum"

    def _set_auto_tuner_csv(self) -> None:
        selected_regions = [k for k, v in self.region_vars.items() if v.get()]
        if selected_regions:
            preferred = selected_regions[0]
            latest = _find_latest_timeseries_csv(
                output_root=Path(self.output_dir_var.get().strip()),
                region_key=preferred,
            )
            if latest is not None:
                chosen = str(latest)
                self.tuner_csv_var.set(chosen)
                self._last_auto_tuner_csv = chosen
                self._tuner_csv_manual = False
                self._append_log(f"対象CSVを自動選択しました: {latest.name}")
                return

        if self._last_result:
            csv_root = self._last_result.get("analysis_csv_dir")
            if csv_root:
                csv_root_path = Path(str(csv_root))
                candidates = sorted(csv_root_path.glob("*/*_timeseries.csv"))
                if candidates:
                    chosen = str(candidates[-1])
                    self.tuner_csv_var.set(chosen)
                    self._last_auto_tuner_csv = chosen
                    self._tuner_csv_manual = False
                    self._append_log("対象CSVを直近実行結果から自動選択しました。")
                    return

        self.tuner_csv_var.set("")
        self._last_auto_tuner_csv = ""
        self._tuner_csv_manual = False
        self._append_log("対象CSVが見つからないためテンプレートを使用します。")

    def _on_open_style_tuner(self) -> None:
        if self._tuner_csv_manual:
            self._refresh_tuner_csv_if_needed()
        else:
            self._set_auto_tuner_csv()
        csv_value = self.tuner_csv_var.get().strip()
        input_csv = Path(csv_value) if csv_value else None
        if input_csv is not None and not input_csv.exists():
            self._append_log(f"対象CSVが見つからないためテンプレートで起動: {input_csv}")
            input_csv = None

        profile_path = default_style_profile_path()

        try:
            launch_style_tuner(
                input_csv=input_csv,
                value_kind=self._resolve_primary_value_kind(),
                title="流域平均雨量（{start} - {end}）",
                sample_mode="synthetic",
                profile_path=profile_path,
                preview_span=self._resolve_current_graph_span(),
                master=self.root,
            )
            self._append_log("グラフスタイル調整を起動しました。")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("起動エラー", f"グラフスタイル調整を起動できませんでした: {exc}")

    def _on_close(self) -> None:
        _save_state(self._collect_state_payload())
        self.root.destroy()

    def _auto_capture_once(self) -> None:
        self._on_capture_shortcut()
        if self._auto_exit_after_capture:
            self.root.after(300, self._on_close)

    def _on_capture_shortcut(self, _event=None):
        try:
            from PIL import ImageGrab
        except Exception:
            messagebox.showerror(
                "スクリーンショット失敗",
                "Pillow(ImageGrab)が利用できません。`uv add pillow` 後に再実行してください。",
            )
            return "break"

        self.root.update_idletasks()
        x = self.root.winfo_rootx()
        y = self.root.winfo_rooty()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        if w <= 0 or h <= 0:
            return "break"

        _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = _SCREENSHOT_DIR / f"zipflow_gui_{stamp}.png"
        image = ImageGrab.grab(bbox=(x, y, x + w, y + h))
        image.save(out_path)
        self._append_log(f"画面スクリーンショットを保存しました: {out_path}")
        self._set_status("スクリーンショット保存完了")
        return "break"

    def run(self) -> None:
        self.root.mainloop()


def launch_zipflow_gui() -> None:
    app = ZipFlowGui()
    app.run()


def launch_zipflow_gui_with_capture(
    *,
    auto_capture_seconds: float | None,
    auto_exit_after_capture: bool,
) -> None:
    app = ZipFlowGui(
        auto_capture_seconds=auto_capture_seconds,
        auto_exit_after_capture=auto_exit_after_capture,
    )
    app.run()
