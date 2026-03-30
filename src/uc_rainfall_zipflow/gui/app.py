# pyright: reportArgumentType=false, reportAttributeAccessIssue=false
from __future__ import annotations

import csv
import json
import math
import os
import shutil
import sys
import tempfile
import threading
import tkinter as tk
from contextlib import ExitStack
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, cast

import pandas as pd

from ..errors import ZipFlowError
from ..excel_application import (
    ExcelRunConfig,
    ExcelSelectedEvent,
    build_excel_filename_prefix,
    collect_excel_event_candidates,
    export_excel_event_candidates_csv,
    resolve_effective_base_date,
    run_excel_mode,
)
from ..graph_builder import build_metric_frame, build_reference_output_paths, render_region_plots_reference
from ..graph_renderer_reference import compute_axis_tops, prepare_reference_window
from ..models import RunConfig
from ..runtime_paths import resolve_path
from ..style_profile import default_style_profile_path, load_style_profile
from ..zip_selector import list_zip_windows
from .excel_mode_panel import ExcelModePanel
from .rain_mode_panel import RainModePanel
from .style_tuner_window import launch_style_tuner
from .types import StyleTunerInput

_DATE_FMT = "%Y-%m-%d"
_GUI_STATE_PATH = resolve_path("config", "uc_rainfall_zipflow", "gui_state.json")
_GUI_HELP_REL_PATH = Path("config") / "uc_rainfall_zipflow" / "gui_help.txt"
_SCREENSHOT_DIR = resolve_path("outputs", "_gui_screenshots")
_GUI_TEST_DIR = resolve_path("outputs", "_gui_test")
_EXCEL_CANDIDATES_DIR = resolve_path("outputs", "excel_candidates")
_EXCEL_INPUT_DIR = resolve_path("data", "excel_input")
_DEV_UI_ENV = "UC_ZIPFLOW_DEV_UI"
_MERGE_DEFAULT_COLUMNS = 2
_MERGE_DEFAULT_ROWS = 4
_RUN_MODES = ("解析雨量データ", "Excelデータ")
_RUNTIME_ENGINES = ("python", "rust_pyo3")

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
_EXCEL_FIXED_REGION_KEYS = ("nishiyoke_higashiyoke",)
_EXCEL_FIXED_OUTPUT_KINDS = ("plots_ref",)
_DEFAULT_GUI_HELP_TEXT = """【流域雨量グラフ作成 ヘルプ】

1. モード
- 解析雨量データ: ZIP入力から流域ごとの出力を作成します。
- Excelデータ: Excelシート時系列から整形グラフを作成します。

2. 基本操作
- 入出力欄で入力元と出力先を指定します。
- 実行設定で対象流域・出力種別・グラフ指標を選びます。
- 「処理を実行」で出力を開始します。

3. 画像マージ
- 「実行後に画像マージ」をONにすると、実行完了後に自動でマージします。
- 「今すぐ画像マージ」で、既存の plots_reference PNG を対象に手動実行できます。
- 行列は「列数」「行数」で指定します（初期値: 2列 x 4行）。
- 最後のページに余りがある場合は空欄のまま出力します。

4. グラフスタイル調整
- 「グラフスタイル調整」で見た目を変更できます。
- 保存して閉じると、次回実行から反映されます。

5. よくあるエラー
- 入力ファイルが見つからない:
  パスを再確認し、読み取り可能な場所を指定してください。
- Excel期間不一致:
  シート名日付と時刻列(B列)の期間整合を確認してください。
- 画像マージ対象なし:
  先に plots_reference のPNGを出力してください。
"""


@dataclass(frozen=True)
class A4MergeSpec:
    columns: int
    rows: int


@dataclass(frozen=True)
class A4LayoutPlan:
    cols: int
    rows: int
    page_count: int
    cell_width_px: int
    cell_height_px: int
    canvas_width_px: int
    canvas_height_px: int


@dataclass(frozen=True)
class A4MergeResult:
    paths: list[Path]
    plan: A4LayoutPlan
    warning: str | None


def choose_a4_layout_plan(
    *,
    image_sizes: list[tuple[int, int]],
    spec: A4MergeSpec,
) -> A4LayoutPlan:
    if not image_sizes:
        raise ValueError("画像がありません。")
    if spec.columns <= 0 or spec.rows <= 0:
        raise ValueError("画像マージ設定が不正です。")

    base_cell_w = max(max(1, int(w)) for w, _ in image_sizes)
    base_cell_h = max(max(1, int(h)) for _, h in image_sizes)
    image_count = len(image_sizes)

    cols = int(spec.columns)
    rows = int(spec.rows)
    capacity = cols * rows
    page_count = int(math.ceil(image_count / capacity))
    return A4LayoutPlan(
        cols=cols,
        rows=rows,
        page_count=page_count,
        cell_width_px=base_cell_w,
        cell_height_px=base_cell_h,
        canvas_width_px=base_cell_w * cols,
        canvas_height_px=base_cell_h * rows,
    )


def merge_pngs_to_a4(
    *,
    input_paths: list[Path],
    output_dir: Path,
    spec: A4MergeSpec,
) -> A4MergeResult:
    png_paths = [path for path in input_paths if path.suffix.lower() == ".png" and path.exists()]
    if not png_paths:
        raise ValueError("マージ対象PNGがありません。")

    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("画像マージには Pillow が必要です。`uv add pillow` を実行してください。") from exc

    with ExitStack() as stack:
        images = [stack.enter_context(Image.open(path)) for path in png_paths]
        sizes = [(int(img.width), int(img.height)) for img in images]
    plan = choose_a4_layout_plan(image_sizes=sizes, spec=spec)

    merged_dir = output_dir / f"_merged_{plan.cols}x{plan.rows}"
    merged_dir.mkdir(parents=True, exist_ok=True)
    capacity = plan.cols * plan.rows
    merged_paths: list[Path] = []

    for page_index in range(plan.page_count):
        start = page_index * capacity
        chunk = png_paths[start : start + capacity]
        if not chunk:
            continue
        canvas = Image.new("RGB", (plan.canvas_width_px, plan.canvas_height_px), "white")
        with ExitStack() as stack:
            page_images = [stack.enter_context(Image.open(path)) for path in chunk]
            for pos, img in enumerate(page_images):
                row = pos // plan.cols
                col = pos % plan.cols
                cell_x = col * plan.cell_width_px
                cell_y = row * plan.cell_height_px
                resized = img.convert("RGB")
                paste_x = cell_x + max(0, (plan.cell_width_px - resized.width) // 2)
                paste_y = cell_y + max(0, (plan.cell_height_px - resized.height) // 2)
                canvas.paste(resized, (paste_x, paste_y))
        out_path = merged_dir / f"merged_{plan.cols}x{plan.rows}_{page_index + 1:03d}.png"
        canvas.save(out_path)
        merged_paths.append(out_path)
    return A4MergeResult(paths=merged_paths, plan=plan, warning=None)


def _parse_date(raw: str, *, field_name: str) -> date:
    try:
        return datetime.strptime(raw.strip(), _DATE_FMT).date()
    except ValueError as exc:
        raise ValueError(f"{field_name} は YYYY-MM-DD 形式で入力してください。") from exc


def _resolve_base_date(start_date: date, end_date: date) -> date:
    day_count = (end_date - start_date).days + 1
    return start_date + timedelta(days=day_count // 2)


def _list_available_region_keys(polygon_dir: Path) -> set[str]:
    from ..regions import load_region_specs

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


def _load_gui_help_text(path: Path) -> str:
    if not path.exists():
        return (
            "ヘルプファイルが見つかりません。\n\n"
            f"対象: {path}\n"
            "管理者に連絡してヘルプファイルを配置してください。"
        )
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return (
            "ヘルプファイルの読み込みに失敗しました。\n\n"
            f"対象: {path}\n"
            f"詳細: {exc}"
        )
    stripped = text.strip()
    if not stripped:
        return (
            "ヘルプファイルが空です。\n\n"
            f"対象: {path}\n"
            "ヘルプ内容を記述してください。"
        )
    return stripped


def _preferred_gui_help_output_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / _GUI_HELP_REL_PATH
    return resolve_path(*_GUI_HELP_REL_PATH.parts)


def _ensure_gui_help_file_exists() -> Path | None:
    target = _preferred_gui_help_output_path()
    if target.exists():
        return target
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_DEFAULT_GUI_HELP_TEXT.strip() + "\n", encoding="utf-8")
        return target
    except Exception:
        return None


def _iter_gui_help_candidates() -> list[Path]:
    exe_dir = Path(sys.executable).resolve().parent
    return [
        exe_dir / _GUI_HELP_REL_PATH,
        exe_dir / "gui_help.txt",
        resolve_path(*_GUI_HELP_REL_PATH.parts),
    ]


def _load_gui_help_text_from_candidates() -> str:
    auto_generated = _ensure_gui_help_file_exists()
    if auto_generated is not None and auto_generated.exists():
        return _load_gui_help_text(auto_generated)
    candidates = _iter_gui_help_candidates()
    for path in candidates:
        if path.exists():
            return _load_gui_help_text(path)
    return _DEFAULT_GUI_HELP_TEXT.strip()


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
        test_mode: bool = False,
        dev_mode: bool | None = None,
    ) -> None:
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("流域雨量グラフ作成（メインウィンドウ）")
        self.root.minsize(980, 680)
        self._help_window: tk.Toplevel | None = None
        self._help_text_widget: tk.Text | None = None

        self._state = _load_state()
        self._is_running = False
        self._last_result: dict[str, object] | None = None
        self._path_rows: list[tuple[ttk.Frame, ttk.Label, ttk.Button]] = []
        self._tuner_csv_manual = False
        self._last_auto_tuner_csv = ""
        self._auto_capture_seconds = auto_capture_seconds
        self._auto_exit_after_capture = auto_exit_after_capture
        self._test_mode = test_mode
        self._bottom_bar_bg = "#E6EAF1"
        self._status_default_fg = "#2A3342"
        self._status_error_fg = "#B71C1C"
        self._saved_rain_region_state: dict[str, bool] | None = None
        self._saved_rain_output_state: dict[str, bool] | None = None
        self._last_plot_ref_png_paths: list[Path] = []
        self._dev_window: tk.Toplevel | None = None
        self._dev_mode = dev_mode

        self._build_vars()
        self._build_menu_bar()
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
        self._open_dev_tools_window_if_enabled()
        if self._auto_capture_seconds is not None and self._auto_capture_seconds >= 0.0:
            delay_ms = int(self._auto_capture_seconds * 1000)
            self.root.after(delay_ms, self._auto_capture_once)
        if self._test_mode:
            self.root.after(450, self._run_startup_test)

    def _place_window_initial(self) -> None:
        self.root.update_idletasks()
        req_w, req_h = self._compute_required_size_across_modes()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        current_w = max(980, req_w)
        current_h = max(680, req_h)
        width = min(current_w, max(960, screen_w - 120))
        height = min(current_h, max(660, screen_h - 140))
        x = max(24, (screen_w - width) // 2)
        y = max(24, (screen_h - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _compute_required_size_across_modes(self) -> tuple[int, int]:
        """モード差分による必要サイズを先に見積もり、初期表示の欠けを防ぐ。"""
        saved_mode = self.run_mode_var.get()
        max_w = 0
        max_h = 0
        for mode in _RUN_MODES:
            self.run_mode_var.set(mode)
            self._update_input_mode_visibility()
            self.root.update_idletasks()
            max_w = max(max_w, int(self.root.winfo_reqwidth()))
            max_h = max(max_h, int(self.root.winfo_reqheight()))
        self.run_mode_var.set(saved_mode)
        self._update_input_mode_visibility()
        self.root.update_idletasks()
        # ラベル折返しやDPI差を考慮して少し余裕を持たせる
        return max_w + 24, max_h + 24

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
        if hasattr(self, "rain_panel"):
            self.rain_panel.set_form_label_minsize(max_label + 8)
        if hasattr(self, "excel_panel"):
            self.excel_panel.set_form_label_minsize(max_label + 8)

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
        self.merge_a4_enabled_var = tk.BooleanVar(value=False)
        self.merge_a4_columns_var = tk.StringVar(value=str(_MERGE_DEFAULT_COLUMNS))
        self.merge_a4_rows_var = tk.StringVar(value=str(_MERGE_DEFAULT_ROWS))
        self.status_var = tk.StringVar(value="待機中")
        self.updated_var = tk.StringVar(value="最終更新: --")
        self.graph_span_var = tk.StringVar(value="自動判定: 3日")
        self.tuner_csv_var = tk.StringVar(value="")
        self.rain_dates_csv_var = tk.StringVar(value="")
        self.rain_dates_excel_var = tk.StringVar(value="")
        self.compute_engine_var = tk.StringVar(value="python")
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
        if self.run_mode_var.get().strip() == "Excelデータ":
            return
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

        self._build_right_pane(right)

        status_bar = tk.Frame(root_pad, bg=self._bottom_bar_bg, height=34)
        status_bar.pack(fill=tk.X, pady=(8, 0))
        status_bar.pack_propagate(False)
        self.status_label = tk.Label(
            status_bar,
            textvariable=self.status_var,
            bg=self._bottom_bar_bg,
            fg=self._status_default_fg,
            anchor="w",
        )
        self.status_label.pack(side=tk.LEFT, padx=(10, 0))
        tk.Label(
            status_bar,
            textvariable=self.updated_var,
            bg=self._bottom_bar_bg,
            fg=self._status_default_fg,
            anchor="w",
        ).pack(side=tk.LEFT, padx=(14, 0))

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_menu_bar(self) -> None:
        menubar = tk.Menu(self.root)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="ヘルプを表示", command=self._on_open_help)
        menubar.add_cascade(label="ヘルプ", menu=help_menu)
        self.root.configure(menu=menubar)

    def _on_open_help(self) -> None:
        text = _load_gui_help_text_from_candidates()
        if self._help_window is not None and self._help_window.winfo_exists():
            self._help_window.deiconify()
            self._help_window.lift()
            body = getattr(self, "_help_text_widget", None)
            if isinstance(body, tk.Text):
                body.configure(state=tk.NORMAL)
                body.delete("1.0", tk.END)
                body.insert("1.0", text)
                body.configure(state=tk.DISABLED)
            return

        win = tk.Toplevel(self.root)
        win.title("ヘルプ")
        win.transient(self.root)
        win.geometry("840x620")
        win.minsize(640, 420)
        outer = ttk.Frame(win, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        ttk.Label(outer, text="流域雨量グラフ作成 ヘルプ", font=("", 12, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        body_wrap = ttk.Frame(outer)
        body_wrap.grid(row=1, column=0, sticky="nsew")
        body_wrap.columnconfigure(0, weight=1)
        body_wrap.rowconfigure(0, weight=1)
        body = tk.Text(body_wrap, wrap=tk.WORD, font=("", 10))
        body.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(body_wrap, orient=tk.VERTICAL, command=body.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        body.configure(yscrollcommand=scroll.set)
        body.insert("1.0", text)
        body.configure(state=tk.DISABLED)

        self._help_window = win
        self._help_text_widget = body

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
        frm.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        self.input_group_frame = frm

        self.mode_input_container = ttk.Frame(frm)
        self.mode_input_container.pack(fill=tk.BOTH, expand=True, pady=(0, 0))
        self.rain_panel = RainModePanel.create(
            self.mode_input_container,
            build_path_row=self._path_row,
            input_zip_var=self.input_zipdir_var,
            start_date_var=self.start_date_var,
            end_date_var=self.end_date_var,
            on_change=self._update_graph_span_label,
            on_import_excel=self._on_import_rain_dates_from_excel,
        )
        self.excel_panel = ExcelModePanel.create(
            self.mode_input_container,
            build_path_row=self._path_row,
            input_excel_var=self.input_excel_var,
            on_log=self._append_log,
        )
        self.input_zip_row = self.rain_panel.input_zip_row
        self.polygon_row = self._path_row(
            frm,
            "ポリゴンディレクトリ",
            self.polygon_dir_var,
            ask_dir=True,
            on_change=self._refresh_region_choices,
        )
        self.output_dir_row = self._path_row(frm, "出力ディレクトリ", self.output_dir_var, ask_dir=True)
        self.start_date_var.trace_add("write", lambda *_: self._update_graph_span_label())
        self.end_date_var.trace_add("write", lambda *_: self._update_graph_span_label())

        self.log_checkbox = ttk.Checkbutton(frm, text="ログを保存する", variable=self.enable_log_var)
        self.log_checkbox.pack(anchor=tk.W, pady=(6, 0))
        self.input_zipdir_var.trace_add(
            "write",
            lambda *_: (
                self.rain_panel.mark_zipdir_changed(),
                self._update_graph_span_label(),
            ),
        )
        self.input_excel_var.trace_add(
            "write",
            lambda *_: self.excel_panel.refresh_candidates(self.input_excel_var.get().strip()),
        )
        self.rain_panel.mark_zipdir_changed()
        self._update_rain_period_input_mode()
        self._reflow_input_group_layout()
        self._update_input_mode_visibility()

    def _reflow_input_group_layout(self) -> None:
        if not hasattr(self, "input_group_frame"):
            return

        # いったんすべて外してから、モードごとに順序を1箇所で再配置する。
        self.mode_input_container.pack_forget()
        self.polygon_row.pack_forget()
        self.output_dir_row.pack_forget()
        self.log_checkbox.pack_forget()

        mode = self.run_mode_var.get().strip()
        if mode == "Excelデータ":
            self.mode_input_container.pack(fill=tk.BOTH, expand=True, pady=(0, 0))
            self.output_dir_row.pack(fill=tk.X, pady=2)
            self.log_checkbox.pack(anchor=tk.W, pady=(6, 0))
            return

        # 解析雨量モード
        self.mode_input_container.pack(fill=tk.BOTH, expand=True, pady=(0, 0))
        self.polygon_row.pack(fill=tk.X, pady=2)
        self.output_dir_row.pack(fill=tk.X, pady=2)
        self.log_checkbox.pack(anchor=tk.W, pady=(6, 0))

    def _build_standard_group(self, parent: ttk.Frame) -> None:
        frm = ttk.LabelFrame(parent, text="実行設定", padding=10)
        frm.pack(fill=tk.X, pady=(0, 8))
        self.standard_group_frame = frm
        def row_block(label: str) -> tuple[ttk.Frame, ttk.Frame]:
            row = ttk.Frame(frm)
            row.pack(fill=tk.X, pady=(2, 4))
            ttk.Label(row, text=label, width=9).pack(side=tk.LEFT, anchor=tk.N)
            body = ttk.Frame(row)
            body.pack(side=tk.LEFT, fill=tk.X, expand=True)
            return row, body

        self.region_row, region_wrap = row_block("対象流域")
        for key in _REGION_LABELS:
            ttk.Checkbutton(region_wrap, text=_REGION_LABELS[key], variable=self.region_vars[key]).pack(
                side=tk.LEFT,
                padx=(0, 10),
            )

        self.output_row, out_wrap = row_block("出力種別")
        for key in _OUTPUT_LABELS:
            ttk.Checkbutton(out_wrap, text=_OUTPUT_LABELS[key], variable=self.output_vars[key]).pack(
                side=tk.LEFT,
                padx=(0, 10),
            )

        self.graph_kind_row, kind_wrap = row_block("グラフ指標")
        for key in _GRAPH_KIND_LABELS:
            ttk.Checkbutton(kind_wrap, text=_GRAPH_KIND_LABELS[key], variable=self.graph_kind_vars[key]).pack(
                side=tk.LEFT,
                padx=(0, 10),
            )
        ttk.Checkbutton(kind_wrap, text="SVGも出力", variable=self.export_svg_var).pack(side=tk.LEFT, padx=(0, 2))

        self.merge_row, merge_wrap = row_block("画像マージ")
        ttk.Checkbutton(merge_wrap, text="実行後に画像マージ", variable=self.merge_a4_enabled_var).pack(
            side=tk.LEFT, padx=(0, 10)
        )
        ttk.Button(merge_wrap, text="今すぐ画像マージ", command=self._on_merge_a4_clicked).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Label(merge_wrap, text="列数").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Entry(merge_wrap, width=4, textvariable=self.merge_a4_columns_var).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(merge_wrap, text="行数").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Entry(merge_wrap, width=4, textvariable=self.merge_a4_rows_var).pack(side=tk.LEFT, padx=(0, 8))

    def _build_action_group(self, parent: ttk.Frame) -> None:
        row = ttk.Frame(parent, padding=(0, 2))
        row.pack(fill=tk.X, pady=(2, 0))
        self.action_group_row = row
        self.run_button = ttk.Button(row, text="処理を実行", command=self._on_run_clicked)
        self.run_button.pack(anchor=tk.W)

    def _build_output_list_group(self, parent: ttk.Frame) -> None:
        frm = ttk.LabelFrame(parent, text="出力一覧", padding=10)
        frm.pack(fill=tk.BOTH, expand=True, pady=(6, 8))
        self.summary_text = tk.Text(frm, height=7, wrap=tk.WORD, font=("", 10))
        self.summary_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        summary_scroll = ttk.Scrollbar(frm, orient=tk.VERTICAL, command=self.summary_text.yview)
        summary_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.summary_text.configure(yscrollcommand=summary_scroll.set)

    def _build_right_pane(self, parent: ttk.Frame) -> None:
        pane = ttk.Frame(parent)
        pane.grid(row=1, column=0, sticky="nsew", pady=(0, 2))
        pane.rowconfigure(0, weight=1, minsize=360)
        pane.rowconfigure(1, weight=0, minsize=120)
        pane.rowconfigure(2, weight=0, minsize=0)
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

        summary = ttk.LabelFrame(pane, text="出力一覧", padding=10)
        summary.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        summary.columnconfigure(0, weight=1)
        summary.rowconfigure(0, weight=1)
        self.summary_text = tk.Text(summary, height=6, wrap=tk.WORD, font=("", 10))
        self.summary_text.grid(row=0, column=0, sticky="nsew")
        summary_scroll = ttk.Scrollbar(summary, orient=tk.VERTICAL, command=self.summary_text.yview)
        summary_scroll.grid(row=0, column=1, sticky="ns")
        self.summary_text.configure(yscrollcommand=summary_scroll.set)

        lower = ttk.Frame(pane)
        lower.grid(row=2, column=0, sticky="nsew")
        lower.columnconfigure(0, weight=1)
        lower.rowconfigure(0, weight=0, minsize=0)

        tuner = ttk.LabelFrame(lower, text="グラフスタイル調整", padding=10)
        tuner.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.tuner_help_title_label = ttk.Label(tuner, text="", font=("", 9, "bold"))
        self.tuner_help_title_label.grid(row=0, column=0, columnspan=3, sticky="w")
        self.tuner_help_line_labels: list[ttk.Label] = []
        for idx in range(4):
            label = ttk.Label(tuner, text="")
            label.grid(row=idx + 1, column=0, columnspan=3, sticky="w")
            self.tuner_help_line_labels.append(label)

        tuner_row = ttk.Frame(tuner)
        tuner_row.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        self.tuner_csv_row = tuner_row
        tuner_row.columnconfigure(1, weight=1)
        label_csv = ttk.Label(tuner_row, text="対象CSV")
        self.tuner_csv_label = label_csv
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
        self._update_style_tuner_help_by_mode()

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
        standard_group = getattr(self, "standard_group_frame", None)
        action_row = getattr(self, "action_group_row", None)
        region_row = getattr(self, "region_row", None)
        output_row = getattr(self, "output_row", None)
        if mode == "Excelデータ":
            self.rain_panel.hide()
            self.excel_panel.refresh_candidates(self.input_excel_var.get().strip())
            self.excel_panel.show()
            self._snapshot_rain_settings()
            self._apply_excel_fixed_settings()
            if region_row is not None:
                region_row.pack_forget()
            if output_row is not None:
                output_row.pack_forget()
        else:
            self.excel_panel.hide()
            self.rain_panel.show()
            self._restore_rain_settings()
            if region_row is not None and region_row.winfo_manager() == "":
                region_row.pack(fill=tk.X, pady=(2, 4))
            if output_row is not None and output_row.winfo_manager() == "":
                output_row.pack(fill=tk.X, pady=(2, 4))
            if standard_group is not None:
                if action_row is not None:
                    standard_group.pack(fill=tk.X, pady=(0, 8), before=action_row)
                else:
                    standard_group.pack(fill=tk.X, pady=(0, 8))
        self._reflow_input_group_layout()
        self._update_rain_period_input_mode()
        self._update_style_tuner_help_by_mode()
        self._update_graph_span_label()

    def _update_style_tuner_help_by_mode(self) -> None:
        if not hasattr(self, "tuner_help_title_label"):
            return
        mode = self.run_mode_var.get().strip()
        if mode == "Excelデータ":
            self.tuner_help_title_label.configure(text="Excelモードの使い方")
            excel_lines = (
                "1. 選択中イベントの先頭1件をプレビューに使います。",
                "2. 対象CSVの指定は使いません（Excel実データ優先）。",
                "3. イベント未選択時はテンプレートデータで起動します。",
                "4. 保存して閉じると次回のグラフ出力に反映されます。",
            )
            for label, text in zip(self.tuner_help_line_labels, excel_lines, strict=False):
                label.configure(text=text)
            if getattr(self, "tuner_csv_row", None) is not None:
                self.tuner_csv_row.grid_remove()
        else:
            self.tuner_help_title_label.configure(text="解析雨量モードの使い方")
            rain_lines = (
                "1. 対象CSVを指定すると、そのCSVでプレビューします。",
                "2. 空欄なら選択中流域の時系列CSV（*_timeseries.csv）を自動で探します。",
                "3. 見つからない場合はテンプレートデータでプレビューします。",
                "4. 保存して閉じると次回のグラフ出力に反映されます。",
            )
            for label, text in zip(self.tuner_help_line_labels, rain_lines, strict=False):
                label.configure(text=text)
            if getattr(self, "tuner_csv_row", None) is not None:
                self.tuner_csv_row.grid()

    def _snapshot_rain_settings(self) -> None:
        if self._saved_rain_region_state is None:
            self._saved_rain_region_state = {k: bool(v.get()) for k, v in self.region_vars.items()}
        if self._saved_rain_output_state is None:
            self._saved_rain_output_state = {k: bool(v.get()) for k, v in self.output_vars.items()}

    def _restore_rain_settings(self) -> None:
        if self._saved_rain_region_state is not None:
            for key, var in self.region_vars.items():
                var.set(bool(self._saved_rain_region_state.get(key, var.get())))
        if self._saved_rain_output_state is not None:
            for key, var in self.output_vars.items():
                var.set(bool(self._saved_rain_output_state.get(key, var.get())))
        self._saved_rain_region_state = None
        self._saved_rain_output_state = None

    def _apply_excel_fixed_settings(self) -> None:
        fixed_regions = set(_EXCEL_FIXED_REGION_KEYS)
        fixed_outputs = set(_EXCEL_FIXED_OUTPUT_KINDS)
        for key, var in self.region_vars.items():
            var.set(key in fixed_regions)
        for key, var in self.output_vars.items():
            var.set(key in fixed_outputs)

    def _append_log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"{stamp}  {message}\n")
        self.log_text.see(tk.END)
        self.updated_var.set(f"最終更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    def _set_status(self, text: str, *, is_error: bool = False) -> None:
        self.status_var.set(text)
        if not hasattr(self, "status_label"):
            return
        if is_error:
            self.status_label.configure(fg=self._status_error_fg)
        else:
            self.status_label.configure(fg=self._status_default_fg)

    def _set_summary(self, text: str) -> None:
        self.summary_text.delete("1.0", tk.END)
        self.summary_text.insert("1.0", text)

    def _update_rain_period_input_mode(self) -> None:
        if not hasattr(self, "rain_panel"):
            return
        # 期間指定の有効/無効は rain_panel 側の period_input_mode で制御する。
        self.rain_panel.refresh_input_mode_state()

    def _update_graph_span_label(self) -> None:
        run_button = getattr(self, "run_button", None)
        def _set_run_enabled(enabled: bool) -> None:
            if run_button is None:
                return
            run_button.configure(state=tk.NORMAL if (enabled and not self._is_running) else tk.DISABLED)

        if self.run_mode_var.get().strip() == "Excelデータ":
            self.graph_span_var.set(f"Excel指定: {self.excel_panel.get_span_label()}")
            _set_run_enabled(True)
            if self.status_var.get().startswith("期間エラー"):
                self._set_status("待機中")
            return
        if self.rain_panel.is_auto_mode():
            selected_dates = self.rain_panel.get_selected_target_dates()
            if selected_dates:
                self.graph_span_var.set(
                    f"解析雨量指定: {self.rain_panel.get_window_mode_label()} / 対象日={len(selected_dates)}件"
                )
                _set_run_enabled(True)
                if self.status_var.get().startswith("期間エラー"):
                    self._set_status("待機中")
            else:
                self.graph_span_var.set("解析雨量指定: 対象日未選択")
                _set_run_enabled(False)
                self._set_status("期間エラー（対象日を選択）", is_error=True)
            return
        try:
            start = _parse_date(self.start_date_var.get(), field_name="開始日")
            end = _parse_date(self.end_date_var.get(), field_name="終了日")
            day_count = (end - start).days + 1
            if day_count in (3, 5):
                self.graph_span_var.set(f"自動判定: {day_count}日")
                _set_run_enabled(True)
                if self.status_var.get().startswith("期間エラー"):
                    self._set_status("待機中")
            else:
                self.graph_span_var.set("自動判定: 期間エラー（3日 or 5日）")
                _set_run_enabled(False)
                self._set_status("期間エラー（3日 or 5日）", is_error=True)
        except ValueError:
            self.graph_span_var.set("自動判定: 日付形式エラー")
            _set_run_enabled(False)
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
            "excel_graph_span": self.excel_panel.get_span(),
            "excel_selected_event_keys": self.excel_panel.get_selected_event_keys(),
            "rain_period_input_mode": self.rain_panel.period_input_mode_var.get().strip(),
            "rain_window_mode": self.rain_panel.get_window_mode(),
            "rain_selected_dates": [
                self.rain_panel.date_listbox.get(i) for i in self.rain_panel.date_listbox.curselection()
            ],
            "rain_dates_csv_path": self.rain_dates_csv_var.get().strip(),
            "rain_dates_excel_path": self.rain_dates_excel_var.get().strip(),
            "rain_compute_engine": self.compute_engine_var.get().strip(),
            "output_dir": self.output_dir_var.get().strip(),
            "polygon_dir": self.polygon_dir_var.get().strip(),
            "period_start": self.start_date_var.get().strip(),
            "period_end": self.end_date_var.get().strip(),
            "selected_regions": [k for k, v in self.region_vars.items() if v.get()],
            "selected_outputs": [k for k, v in self.output_vars.items() if v.get()],
            "ref_graph_kinds": [k for k, v in self.graph_kind_vars.items() if v.get()],
            "enable_log": bool(self.enable_log_var.get()),
            "export_svg": bool(self.export_svg_var.get()),
            "merge_a4_enabled": bool(self.merge_a4_enabled_var.get()),
            "merge_a4_columns": self.merge_a4_columns_var.get().strip(),
            "merge_a4_rows": self.merge_a4_rows_var.get().strip(),
        }

    def _apply_loaded_state(self) -> None:
        state = self._state
        mode = str(state.get("run_mode", self.run_mode_var.get()))
        self.run_mode_var.set(mode if mode in _RUN_MODES else _RUN_MODES[0])
        self.input_zipdir_var.set(str(state.get("input_zipdir", self.input_zipdir_var.get())))
        self.input_excel_var.set(str(state.get("input_excel", self.input_excel_var.get())))
        self.rain_panel.period_input_mode_var.set(
            str(state.get("rain_period_input_mode", self.rain_panel.period_input_mode_var.get()))
        )
        self.rain_panel.window_mode_var.set(str(state.get("rain_window_mode", self.rain_panel.get_window_mode())))
        self.rain_dates_csv_var.set(str(state.get("rain_dates_csv_path", self.rain_dates_csv_var.get())))
        self.rain_dates_excel_var.set(str(state.get("rain_dates_excel_path", self.rain_dates_excel_var.get())))
        loaded_engine = str(state.get("rain_compute_engine", self.compute_engine_var.get())).strip()
        self.compute_engine_var.set(loaded_engine if loaded_engine in _RUNTIME_ENGINES else "python")
        self.rain_panel.mark_zipdir_changed()
        self.rain_panel.refresh_candidates(self.input_zipdir_var.get().strip(), force=False)
        selected_rain_dates = set(cast(list[str], state.get("rain_selected_dates", [])))
        if selected_rain_dates and self.rain_panel.date_listbox.size() > 0:
            self.rain_panel.date_listbox.selection_clear(0, tk.END)
            for i in range(self.rain_panel.date_listbox.size()):
                val = self.rain_panel.date_listbox.get(i)
                if val in selected_rain_dates:
                    self.rain_panel.date_listbox.selection_set(i)
            self.rain_panel._update_selected_count()
        self.excel_panel.refresh_candidates(self.input_excel_var.get().strip())
        self.excel_panel.span_var.set(str(state.get("excel_graph_span", self.excel_panel.get_span())))
        selected_excel = set(
            cast(
                list[str],
                state.get("excel_selected_event_keys", state.get("excel_selected_sheets", [])),
            )
        )
        self.excel_panel.select_by_event_keys(selected_excel)
        self.output_dir_var.set(str(state.get("output_dir", self.output_dir_var.get())))
        self.polygon_dir_var.set(str(state.get("polygon_dir", self.polygon_dir_var.get())))
        self.start_date_var.set(str(state.get("period_start", self.start_date_var.get())))
        self.end_date_var.set(str(state.get("period_end", self.end_date_var.get())))
        self.enable_log_var.set(bool(state.get("enable_log", self.enable_log_var.get())))
        self.export_svg_var.set(bool(state.get("export_svg", self.export_svg_var.get())))
        self.merge_a4_enabled_var.set(bool(state.get("merge_a4_enabled", self.merge_a4_enabled_var.get())))
        self.merge_a4_columns_var.set(str(state.get("merge_a4_columns", self.merge_a4_columns_var.get())))
        self.merge_a4_rows_var.set(str(state.get("merge_a4_rows", self.merge_a4_rows_var.get())))

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
        self._saved_rain_region_state = {k: bool(v.get()) for k, v in self.region_vars.items()}
        self._saved_rain_output_state = {k: bool(v.get()) for k, v in self.output_vars.items()}
        self._update_input_mode_visibility()

    def _on_import_rain_dates_csv(self) -> None:
        initial_csv = self.rain_dates_csv_var.get().strip()
        if initial_csv:
            initial_dir = str(Path(initial_csv).parent)
            initial_file = Path(initial_csv).name
        else:
            initial_dir = str(_EXCEL_CANDIDATES_DIR if _EXCEL_CANDIDATES_DIR.exists() else Path("."))
            initial_file = ""
        selected = filedialog.askopenfilename(
            title="候補日CSVを選択",
            initialdir=initial_dir,
            initialfile=initial_file,
            filetypes=[("CSV", "*.csv"), ("すべて", "*.*")],
        )
        if not selected:
            return

        csv_path = Path(selected)
        self.rain_dates_csv_var.set(str(csv_path))
        try:
            parsed_dates, invalid_count = self._read_event_dates_csv(csv_path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("CSV読込エラー", str(exc))
            self._append_log(f"[ERROR] 候補日CSV読込失敗: {exc}")
            return
        if not parsed_dates:
            messagebox.showwarning("候補日CSV取込", "有効な event_date が見つかりませんでした。")
            self._append_log("候補日CSV取込: 有効日付なし")
            return

        if not self.rain_panel.is_auto_mode():
            self.rain_panel.period_input_mode_var.set("auto_dates")
        self.rain_panel.refresh_candidates(self.input_zipdir_var.get().strip(), force=False)
        if self.rain_panel.date_listbox.size() == 0:
            messagebox.showwarning("候補日CSV取込", "候補日が空のため、CSV内容を反映できませんでした。")
            self._append_log("候補日CSV取込: 候補日リストが空")
            return

        result = self.rain_panel.apply_target_dates(parsed_dates)
        unmatched = cast(list[str], result["unmatched_dates"])
        preview = "\n".join(unmatched[:8])
        extra = max(0, len(unmatched) - 8)
        if extra > 0:
            preview += f"\n... 他 {extra} 件"
        summary = (
            f"読込件数: {result['requested_count']} 件\n"
            f"選択反映: {result['matched_count']} 件\n"
            f"不一致: {result['unmatched_count']} 件\n"
            f"日付形式不正: {invalid_count} 件"
        )
        if unmatched:
            summary += f"\n\n不一致日付（先頭）:\n{preview}"
        messagebox.showinfo("候補日CSV取込", summary)
        self._append_log(
            "候補日CSV取込: "
            f"requested={result['requested_count']} matched={result['matched_count']} "
            f"unmatched={result['unmatched_count']} invalid={invalid_count} file={csv_path}"
        )
        self._update_graph_span_label()
        _save_state(self._collect_state_payload())

    def _on_import_rain_dates_from_excel(self) -> None:
        initial_excel = self.rain_dates_excel_var.get().strip() or self.input_excel_var.get().strip()
        if initial_excel:
            initial_dir = str(Path(initial_excel).parent)
            initial_file = Path(initial_excel).name
        else:
            initial_dir = str(_EXCEL_INPUT_DIR if _EXCEL_INPUT_DIR.exists() else Path("."))
            initial_file = ""
        selected = filedialog.askopenfilename(
            title="候補日抽出元Excelを選択",
            initialdir=initial_dir,
            initialfile=initial_file,
            filetypes=[("Excel", "*.xlsx;*.xls"), ("すべて", "*.*")],
        )
        if not selected:
            return

        excel_path = Path(selected)
        self.rain_dates_excel_var.set(str(excel_path))
        try:
            candidates = collect_excel_event_candidates(excel_path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Excel読込エラー", str(exc))
            self._append_log(f"[ERROR] Excel候補日取込失敗: {exc}")
            return
        if not candidates:
            messagebox.showwarning("Excel候補日取込", "日付解釈できるシートが見つかりませんでした。")
            self._append_log("Excel候補日取込: 有効候補なし")
            return

        parsed_dates = sorted({item.event_date for item in candidates})
        if not self.rain_panel.is_auto_mode():
            self.rain_panel.period_input_mode_var.set("auto_dates")
        self.rain_panel.refresh_candidates(self.input_zipdir_var.get().strip(), force=False)
        if self.rain_panel.date_listbox.size() == 0:
            messagebox.showwarning("Excel候補日取込", "候補日が空のため、Excel内容を反映できませんでした。")
            self._append_log("Excel候補日取込: 候補日リストが空")
            return

        result = self.rain_panel.apply_target_dates(parsed_dates)
        unmatched = cast(list[str], result["unmatched_dates"])
        preview = "\n".join(unmatched[:8])
        extra = max(0, len(unmatched) - 8)
        if extra > 0:
            preview += f"\n... 他 {extra} 件"
        summary = (
            f"Excel候補シート件数: {len(candidates)} 件\n"
            f"ユニーク日付数: {len(parsed_dates)} 件\n"
            f"選択反映: {result['matched_count']} 件\n"
            f"不一致: {result['unmatched_count']} 件"
        )
        if unmatched:
            summary += f"\n\n不一致日付（先頭）:\n{preview}"
        messagebox.showinfo("Excel候補日取込", summary)
        self._append_log(
            "Excel候補日取込: "
            f"sheets={len(candidates)} unique_dates={len(parsed_dates)} "
            f"matched={result['matched_count']} unmatched={result['unmatched_count']} file={excel_path}"
        )
        self._update_graph_span_label()
        _save_state(self._collect_state_payload())

    def _read_event_dates_csv(self, csv_path: Path) -> tuple[list[date], int]:
        if not csv_path.exists():
            raise ValueError(f"CSVファイルが見つかりません: {csv_path}")
        parsed: list[date] = []
        invalid_count = 0
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or "event_date" not in reader.fieldnames:
                raise ValueError("CSVに event_date 列がありません。")
            for row in reader:
                raw = str((row.get("event_date") or "")).strip()
                if not raw:
                    continue
                try:
                    parsed.append(datetime.strptime(raw, _DATE_FMT).date())
                except ValueError:
                    invalid_count += 1
        return parsed, invalid_count

    def _load_timeseries_frame_for_plot(self, csv_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
        frame = pd.read_csv(csv_path, encoding="utf-8-sig")
        if "observed_at_jst" not in frame.columns:
            raise ZipFlowError(f"時系列CSVに observed_at_jst 列がありません: {csv_path}", exit_code=5)
        if "weighted_sum_mm" not in frame.columns:
            raise ZipFlowError(f"時系列CSVに weighted_sum_mm 列がありません: {csv_path}", exit_code=5)
        if "weighted_mean_mm" not in frame.columns:
            raise ZipFlowError(f"時系列CSVに weighted_mean_mm 列がありません: {csv_path}", exit_code=5)
        observed_at = pd.to_datetime(frame["observed_at_jst"], errors="coerce")
        if observed_at.isna().any():
            raise ZipFlowError(f"時系列CSVの observed_at_jst が不正です: {csv_path}", exit_code=5)
        sum_values = pd.to_numeric(frame["weighted_sum_mm"], errors="coerce").fillna(0.0)
        mean_values = pd.to_numeric(frame["weighted_mean_mm"], errors="coerce").fillna(0.0)
        frame_sum = build_metric_frame(
            observed_at=observed_at.to_list(),
            weighted_sum=sum_values.astype(float).to_list(),
        )
        frame_mean = build_metric_frame(
            observed_at=observed_at.to_list(),
            weighted_sum=mean_values.astype(float).to_list(),
        )
        return frame_sum, frame_mean

    def _compute_shared_axis_tops_for_batch(
        self,
        *,
        plot_jobs: list[dict[str, Any]],
    ) -> dict[str, dict[tuple[str, str], tuple[float, float]]]:
        merged: dict[str, dict[tuple[str, str], tuple[float, float]]] = {}
        style_cache: dict[Path | None, Any] = {}
        for job in plot_jobs:
            cfg = cast(RunConfig, job["config"])
            region_key = cast(str, job["region_key"])
            frame_sum = cast(pd.DataFrame, job["frame_sum"])
            frame_mean = cast(pd.DataFrame, job["frame_mean"])
            style_key = cfg.style_profile_path
            if style_key not in style_cache:
                style_cache[style_key] = load_style_profile(style_key)
            style = style_cache[style_key]
            base_date = cast(date, cfg.reference_base_date or cfg.base_date)
            target = merged.setdefault(region_key, {})
            for span in cfg.graph_spans:
                span_days = 3 if span == "3d" else 5
                center = datetime.combine(base_date, datetime.min.time())
                start = center - timedelta(days=span_days // 2)
                end = start + timedelta(hours=(span_days * 24) - 1)
                for kind in cfg.ref_graph_kinds:
                    frame_src = frame_sum if kind == "sum" else frame_mean
                    span_frame = frame_src[(frame_src["observed_at"] >= start) & (frame_src["observed_at"] <= end)]
                    window = prepare_reference_window(span_frame)
                    tops = compute_axis_tops(
                        left_max=float(window["rainfall_mm"].max()),
                        right_max=float(window["cumulative_mm"].max()),
                        left_top_default=float(style.left_axis_top),
                        right_top_default=float(style.right_axis_top),
                    )
                    prev = target.get((span, kind))
                    if prev is None:
                        target[(span, kind)] = tops
                    else:
                        target[(span, kind)] = (max(prev[0], tops[0]), max(prev[1], tops[1]))
        return merged

    def _is_dev_ui_enabled(self) -> bool:
        if self._dev_mode is not None:
            return bool(self._dev_mode)
        return os.environ.get(_DEV_UI_ENV, "").strip().lower() in {"1", "true", "yes", "on"}

    def _open_dev_tools_window_if_enabled(self) -> None:
        if not self._is_dev_ui_enabled():
            return
        if self._dev_window is not None and self._dev_window.winfo_exists():
            return
        win = tk.Toplevel(self.root)
        win.title("開発者ツール")
        win.resizable(False, False)
        win.transient(self.root)
        frame = ttk.Frame(win, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="開発者向け補助機能", font=("", 10, "bold")).pack(anchor=tk.W, pady=(0, 6))
        ttk.Button(frame, text="解析雨量: 候補日CSV取込", command=self._on_import_rain_dates_csv).pack(
            fill=tk.X, pady=(0, 4)
        )
        ttk.Label(frame, text="解析雨量: 計算エンジン").pack(anchor=tk.W, pady=(8, 2))
        ttk.Combobox(
            frame,
            textvariable=self.compute_engine_var,
            values=_RUNTIME_ENGINES,
            state="readonly",
            width=16,
        ).pack(anchor=tk.W, fill=tk.X, pady=(0, 4))
        ttk.Button(frame, text="Excel: 候補日CSV出力", command=self._on_export_excel_candidates_csv).pack(
            fill=tk.X, pady=(0, 4)
        )
        ttk.Button(
            frame,
            text="解析雨量: 中間JSONからグラフ再出力",
            command=self._on_render_from_intermediate_json,
        ).pack(fill=tk.X, pady=(0, 4))
        ttk.Label(
            frame,
            text=f"表示条件: 環境変数 {_DEV_UI_ENV}=1",
        ).pack(anchor=tk.W, pady=(6, 0))
        self._dev_window = win

    def _on_render_from_intermediate_json(self) -> None:
        initial_path = Path(self.output_dir_var.get().strip()) / "plots_reference" / "_intermediate.json"
        selected = filedialog.askopenfilename(
            title="中間JSONを選択",
            initialdir=str(initial_path.parent) if initial_path.parent.exists() else "",
            initialfile=initial_path.name,
            filetypes=[("JSON", "*.json"), ("すべて", "*.*")],
        )
        if not selected:
            return
        json_path = Path(selected)
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            jobs_raw = payload.get("jobs")
            if not isinstance(jobs_raw, list) or not jobs_raw:
                raise ValueError("jobs が空、または不正です。")
            style_path = default_style_profile_path()
            style = load_style_profile(style_path if style_path.exists() else None)
            output_dir = json_path.parent
            export_svg = bool(self.export_svg_var.get())
            render_jobs: list[dict[str, Any]] = []
            shared_axis_tops: dict[str, dict[tuple[str, str], tuple[float, float]]] = {}
            for idx, job in enumerate(jobs_raw, start=1):
                if not isinstance(job, dict):
                    raise ValueError(f"jobs[{idx}] の形式が不正です。")
                region_key = str(job.get("region_key") or "").strip()
                if not region_key:
                    raise ValueError(f"jobs[{idx}].region_key が不正です。")
                region_label = str(job.get("region_label") or region_key).strip() or region_key
                base_date_raw = str(job.get("reference_base_date") or "").strip()
                if not base_date_raw:
                    raise ValueError(f"jobs[{idx}].reference_base_date が不正です。")
                base_date = _parse_date(base_date_raw, field_name="reference_base_date")
                graph_spans_raw = job.get("graph_spans")
                ref_graph_kinds_raw = job.get("ref_graph_kinds")
                observed_at_raw = job.get("observed_at_jst")
                sum_raw = job.get("weighted_sum_mm")
                mean_raw = job.get("weighted_mean_mm")
                if not isinstance(graph_spans_raw, list) or not graph_spans_raw:
                    raise ValueError(f"jobs[{idx}].graph_spans が不正です。")
                if not isinstance(ref_graph_kinds_raw, list) or not ref_graph_kinds_raw:
                    raise ValueError(f"jobs[{idx}].ref_graph_kinds が不正です。")
                if (
                    not isinstance(observed_at_raw, list)
                    or not isinstance(sum_raw, list)
                    or not isinstance(mean_raw, list)
                ):
                    raise ValueError(f"jobs[{idx}] の時系列配列が不正です。")
                observed_at = pd.to_datetime(observed_at_raw, errors="coerce")
                if observed_at.isna().any():
                    raise ValueError(f"jobs[{idx}].observed_at_jst に不正値があります。")
                frame_sum = build_metric_frame(
                    observed_at=observed_at.to_list(),
                    weighted_sum=[float(v) if v is not None else 0.0 for v in sum_raw],
                )
                frame_mean = build_metric_frame(
                    observed_at=observed_at.to_list(),
                    weighted_sum=[float(v) if v is not None else 0.0 for v in mean_raw],
                )
                graph_spans = tuple(str(v) for v in graph_spans_raw if str(v))
                ref_graph_kinds = tuple(str(v) for v in ref_graph_kinds_raw if str(v))
                if not graph_spans or not ref_graph_kinds:
                    raise ValueError(f"jobs[{idx}] の graph_spans/ref_graph_kinds が空です。")
                axis_target = shared_axis_tops.setdefault(region_key, {})
                for span in graph_spans:
                    span_days = 3 if span == "3d" else 5
                    center = datetime.combine(base_date, datetime.min.time())
                    start = center - timedelta(days=span_days // 2)
                    end = start + timedelta(hours=(span_days * 24) - 1)
                    for kind in ref_graph_kinds:
                        frame_src = frame_sum if kind == "sum" else frame_mean
                        span_frame = frame_src[(frame_src["observed_at"] >= start) & (frame_src["observed_at"] <= end)]
                        window = prepare_reference_window(span_frame)
                        tops = compute_axis_tops(
                            left_max=float(window["rainfall_mm"].max()),
                            right_max=float(window["cumulative_mm"].max()),
                            left_top_default=float(style.left_axis_top),
                            right_top_default=float(style.right_axis_top),
                        )
                        prev = axis_target.get((span, kind))
                        if prev is None:
                            axis_target[(span, kind)] = tops
                        else:
                            axis_target[(span, kind)] = (max(prev[0], tops[0]), max(prev[1], tops[1]))
                render_jobs.append(
                    {
                        "region_key": region_key,
                        "region_label": region_label,
                        "base_date": base_date,
                        "graph_spans": graph_spans,
                        "ref_graph_kinds": ref_graph_kinds,
                        "frame_sum": frame_sum,
                        "frame_mean": frame_mean,
                    }
                )

            output_count = 0
            rendered_paths: list[Path] = []
            for job in render_jobs:
                generated = render_region_plots_reference(
                    frame_sum=cast(pd.DataFrame, job["frame_sum"]),
                    frame_mean=cast(pd.DataFrame, job["frame_mean"]),
                    region_key=cast(str, job["region_key"]),
                    region_label=cast(str, job["region_label"]),
                    output_dir=output_dir,
                    base_date=cast(date, job["base_date"]),
                    graph_spans=cast(tuple[str, ...], job["graph_spans"]),
                    ref_graph_kinds=cast(tuple[str, ...], job["ref_graph_kinds"]),
                    export_svg=export_svg,
                    on_conflict="rename",
                    style=style,
                    axis_tops=shared_axis_tops.get(cast(str, job["region_key"]), {}),
                )
                output_count += len(generated)
                rendered_paths.extend(generated)
            merge_result = self._merge_plot_ref_pngs_to_a4(
                png_paths=[p for p in rendered_paths if p.suffix.lower() == ".png"],
                output_dir=output_dir,
            )
            merged_paths = merge_result.paths
            summary = (
                f"中間JSON再出力: jobs={len(render_jobs)} outputs={output_count} "
                f"merged={len(merged_paths)} source={json_path}"
            )
            self._append_log(
                summary
            )
            if merge_result.warning:
                self._append_log(f"[WARN] {merge_result.warning}")
            messagebox.showinfo(
                "中間JSON再出力",
                "再出力が完了しました。\n\n"
                f"入力: {json_path}\n"
                f"出力先: {output_dir}\n"
                f"出力数: {output_count}\n"
                f"画像マージ出力数: {len(merged_paths)}\n"
                f"レイアウト: {merge_result.plan.cols}x{merge_result.plan.rows} / "
                f"pages={merge_result.plan.page_count}",
            )
        except Exception as exc:  # noqa: BLE001
            self._append_log(f"[ERROR] 中間JSON再出力失敗: {exc}")
            messagebox.showerror("中間JSON再出力エラー", str(exc))

    def _build_a4_merge_spec(self) -> A4MergeSpec:
        try:
            columns = int(float(self.merge_a4_columns_var.get().strip()))
            rows = int(float(self.merge_a4_rows_var.get().strip()))
        except ValueError as exc:
            raise ValueError("画像マージ設定（列数/行数）の形式が不正です。") from exc
        if columns <= 0:
            raise ValueError("画像マージ設定の列数は1以上で指定してください。")
        if rows <= 0:
            raise ValueError("画像マージ設定の行数は1以上で指定してください。")
        return A4MergeSpec(columns=columns, rows=rows)

    def _merge_plot_ref_pngs_to_a4(self, *, png_paths: list[Path], output_dir: Path) -> A4MergeResult:
        spec = self._build_a4_merge_spec()
        return merge_pngs_to_a4(
            input_paths=png_paths,
            output_dir=output_dir,
            spec=spec,
        )

    def _on_export_excel_candidates_csv(self) -> None:
        excel_paths = self.excel_panel.get_input_excel_paths()
        if not excel_paths:
            messagebox.showerror("入力エラー", "Excel候補日CSV出力では入力Excelファイルを指定してください。")
            return
        if len(excel_paths) != 1:
            messagebox.showerror("入力エラー", "Excel候補日CSV出力は1ファイルずつ実行してください。")
            return
        input_excel = excel_paths[0]
        if not input_excel.exists():
            messagebox.showerror("入力エラー", f"入力Excelファイルが見つかりません: {input_excel}")
            return

        output_all_csv = _EXCEL_CANDIDATES_DIR / f"{input_excel.stem}_候補日付リスト.csv"
        output_unique_csv = _EXCEL_CANDIDATES_DIR / f"{input_excel.stem}_候補日付一覧_unique.csv"
        try:
            result = export_excel_event_candidates_csv(
                input_excel=input_excel,
                output_all_csv=output_all_csv,
                output_unique_csv=output_unique_csv,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("CSV出力エラー", str(exc))
            self._append_log(f"[ERROR] Excel候補日CSV出力失敗: {exc}")
            return

        self._append_log(
            "Excel候補日CSVを出力しました: "
            f"candidates={result['candidate_count']} unique={result['unique_date_count']}"
        )
        messagebox.showinfo(
            "候補日CSV出力完了",
            "Excel候補日CSVを2件出力しました。\n\n"
            f"詳細一覧:\n{result['output_all_csv']}\n\n"
            f"重複除去一覧:\n{result['output_unique_csv']}\n\n"
            "利用用途:\n"
            "- 重複除去一覧（*_候補日付一覧_unique.csv）は、\n"
            "  解析雨量モードの「候補日CSV取込」ボタンで\n"
            "  対象日を一括指定する用途に使えます。",
        )

    def _build_rain_run_configs(self) -> tuple[list[RunConfig], int]:
        mode = self.run_mode_var.get().strip()
        if mode == "Excelデータ":
            raise ValueError("内部エラー: Excelモードは _validate_excel_for_run を使用してください。")

        region_keys = tuple(k for k, v in self.region_vars.items() if v.get())
        if not region_keys:
            raise ValueError("対象流域を1つ以上選択してください。")
        output_kinds = tuple(k for k, v in self.output_vars.items() if v.get())
        if not output_kinds:
            raise ValueError("出力種別を1つ以上選択してください。")
        graph_kinds = tuple(k for k, v in self.graph_kind_vars.items() if v.get())
        if not graph_kinds:
            raise ValueError("グラフ指標を1つ以上選択してください。")
        engine = self.compute_engine_var.get().strip()
        if engine not in _RUNTIME_ENGINES:
            raise ValueError(f"計算エンジンが不正です: {engine}")

        default_style_path = default_style_profile_path()
        style_path = default_style_path if default_style_path.exists() else None
        if self.rain_panel.is_auto_mode():
            targets = self.rain_panel.get_selected_target_dates()
            if not targets:
                raise ValueError("対象日から自動設定では対象日を1件以上選択してください。")
            window_mode = self.rain_panel.get_window_mode()
            day_count = 5 if window_mode == "5d" else 3
            graph_spans = ("5d",) if window_mode == "5d" else ("3d",)
            configs: list[RunConfig] = []
            for target_date in targets:
                start_dt, end_dt, _ = self.rain_panel.build_window_for_date(target_date)
                graph_base_date = resolve_effective_base_date(target_date, window_mode)
                configs.append(
                    RunConfig(
                        base_date=target_date,
                        reference_base_date=graph_base_date,
                        input_zipdir=Path(self.input_zipdir_var.get().strip()),
                        output_root=Path(self.output_dir_var.get().strip()),
                        polygon_dir=Path(self.polygon_dir_var.get().strip()),
                        enable_log=bool(self.enable_log_var.get()),
                        export_svg=bool(self.export_svg_var.get()),
                        window_mode="range",
                        days_before=0,
                        days_after=0,
                        start_date=start_dt.date(),
                        end_date=end_dt.date(),
                        graph_spans=graph_spans,
                        ref_graph_kinds=graph_kinds,
                        style_profile_path=style_path,
                        region_keys=region_keys,
                        output_kinds=output_kinds,
                        on_conflict="rename",
                        engine=engine,
                    )
                )
            return configs, day_count

        start = _parse_date(self.start_date_var.get(), field_name="開始日")
        end = _parse_date(self.end_date_var.get(), field_name="終了日")
        if end < start:
            raise ValueError("終了日は開始日以降にしてください。")
        day_count = (end - start).days + 1
        if day_count not in (3, 5):
            raise ValueError("期間は 3日 または 5日で指定してください。")
        config = RunConfig(
            base_date=_resolve_base_date(start, end),
            reference_base_date=None,
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
            engine=engine,
        )
        return [config], day_count

    def _validate_excel_for_run(self) -> ExcelRunConfig:
        input_excels = tuple(self.excel_panel.get_input_excel_paths())
        if not input_excels:
            raise ValueError("Excelモードでは入力Excelファイルを1件以上指定してください。")
        missing = [p for p in input_excels if not p.exists()]
        if missing:
            raise ValueError(f"入力Excelファイルが見つかりません: {missing[0]}")
        selected_ui = self.excel_panel.get_selected_events()
        if not selected_ui:
            raise ValueError("Excelモードではイベント候補を1件以上選択してください。")
        selected_events = tuple(
            ExcelSelectedEvent(
                source_path=item.source_path,
                source_alias=item.source_alias,
                sheet_name=item.sheet_name,
                event_date=item.event_date,
                is_resplit=item.is_resplit,
            )
            for item in selected_ui
        )
        graph_kinds = tuple(k for k, v in self.graph_kind_vars.items() if v.get())
        if not graph_kinds:
            raise ValueError("グラフ指標を1つ以上選択してください。")
        span = self.excel_panel.get_span()
        if span not in ("5d", "3d_left", "3d_center", "3d_right"):
            raise ValueError("Excelモードのグラフ期間が不正です。")
        default_style_path = default_style_profile_path()
        style_path = default_style_path if default_style_path.exists() else None
        return ExcelRunConfig(
            input_excels=input_excels,
            output_root=Path(self.output_dir_var.get().strip()),
            selected_events=selected_events,
            graph_span=span,
            ref_graph_kinds=graph_kinds,
            export_svg=bool(self.export_svg_var.get()),
            enable_log=bool(self.enable_log_var.get()),
            style_profile_path=style_path,
            on_conflict="rename",
        )

    def _resolve_conflict_policy_for_excel(self, config: ExcelRunConfig) -> str | None:
        expected: list[Path] = []
        for event in config.selected_events:
            base_effective = resolve_effective_base_date(event.event_date, config.graph_span)
            expected.extend(
                build_reference_output_paths(
                    output_dir=config.output_root / "plots_reference",
                    region_keys=(config.region_key,),
                    base_date=base_effective,
                    graph_spans=("5d" if config.graph_span == "5d" else "3d",),
                    ref_graph_kinds=config.ref_graph_kinds,
                    export_svg=config.export_svg,
                    filename_prefix=build_excel_filename_prefix(event.source_alias),
                )
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

    def _resolve_conflict_policy_for_plot_ref(self, config: RunConfig) -> str | None:
        if "plots_ref" not in config.output_kinds:
            return config.on_conflict
        reference_base_date = config.reference_base_date or config.base_date
        expected = build_reference_output_paths(
            output_dir=config.output_root / "plots_reference",
            region_keys=config.region_keys,
            base_date=reference_base_date,
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

    def _resolve_conflict_policy_for_plot_ref_batch(self, configs: list[RunConfig]) -> str | None:
        if not configs:
            return "rename"
        expected: list[Path] = []
        for cfg in configs:
            if "plots_ref" not in cfg.output_kinds:
                continue
            reference_base_date = cfg.reference_base_date or cfg.base_date
            expected.extend(
                build_reference_output_paths(
                    output_dir=cfg.output_root / "plots_reference",
                    region_keys=cfg.region_keys,
                    base_date=reference_base_date,
                    graph_spans=cfg.graph_spans,
                    ref_graph_kinds=cfg.ref_graph_kinds,
                    export_svg=cfg.export_svg,
                )
            )
        if not expected:
            return configs[0].on_conflict

        conflicts = sorted({p for p in expected if p.exists()}, key=lambda p: str(p))
        if not conflicts:
            return configs[0].on_conflict

        preview = "\n".join(str(p) for p in conflicts[:8])
        if len(conflicts) > 8:
            preview += f"\n... 他 {len(conflicts) - 8} 件"
        action = messagebox.askyesnocancel(
            "出力先の重複確認（全対象日）",
            "既存のグラフファイルが見つかりました（全対象日まとめて判定）。\n"
            "はい: すべて上書き\n"
            "いいえ: すべて別名保存(_v2, _v3...)\n"
            "キャンセル: 実行中止\n\n"
            f"重複候補:\n{preview}",
        )
        if action is None:
            return None
        if action is True:
            return "overwrite"
        return "rename"

    def _confirm_excel_run(self, config: ExcelRunConfig) -> bool:
        span_label = self.excel_panel.get_span_label()
        kind_labels = [str(_GRAPH_KIND_LABELS.get(k, k)) for k in config.ref_graph_kinds]
        lines: list[str] = []
        for event in config.selected_events:
            lines.append(
                f"- [{event.source_alias}] {event.sheet_name} ({event.event_date:%Y-%m-%d})"
            )
        preview = "\n".join(lines[:20])
        if len(lines) > 20:
            preview += f"\n... 他 {len(lines) - 20} 件"
        return bool(
            messagebox.askyesno(
                "Excelモード実行確認",
                "以下のイベントで実行します。\n\n"
                f"件数: {len(config.selected_events)} 件\n"
                f"入力Excel数: {len(config.input_excels)} 件\n"
                f"グラフ期間: {span_label}\n"
                f"グラフ指標: {', '.join(kind_labels)}\n\n"
                f"{preview}\n\n"
                "この内容で実行しますか？",
            )
        )

    def _write_intermediate_json(
        self,
        *,
        output_root: Path,
        jobs: list[dict[str, Any]],
        filename: str = "_intermediate.json",
        source_mode: str = "rain",
    ) -> Path:
        out_dir = output_root / "plots_reference"
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "format": "uc_rainfall_zipflow.intermediate.v1",
            "source_mode": source_mode,
            "generated_at_jst": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "job_count": len(jobs),
            "jobs": jobs,
        }
        out_path = out_dir / filename
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return out_path

    def _extract_plot_ref_png_paths_from_result(self, result: dict[str, object]) -> list[Path]:
        raw = result.get("plot_ref_png_paths")
        paths: list[Path] = []
        if isinstance(raw, list):
            for value in raw:
                if not isinstance(value, str):
                    continue
                path = Path(value)
                if path.suffix.lower() != ".png":
                    continue
                if path.exists():
                    paths.append(path)
        return paths

    def _list_plot_ref_png_paths_from_output_dir(self) -> list[Path]:
        root = Path(self.output_dir_var.get().strip() or ".") / "plots_reference"
        if not root.exists():
            return []
        files = [p for p in root.glob("*.png") if p.is_file()]
        files.sort(key=lambda path: path.name)
        return files

    def _resolve_latest_plot_ref_png_paths(self) -> list[Path]:
        if self._last_plot_ref_png_paths:
            existing = [p for p in self._last_plot_ref_png_paths if p.exists() and p.suffix.lower() == ".png"]
            if existing:
                return existing
        return self._list_plot_ref_png_paths_from_output_dir()

    def _run_a4_merge_and_attach(
        self,
        *,
        result: dict[str, object],
        png_paths: list[Path],
        output_dir: Path,
    ) -> dict[str, object]:
        merged = self._merge_plot_ref_pngs_to_a4(png_paths=png_paths, output_dir=output_dir)
        result["merged_a4_count"] = len(merged.paths)
        result["merged_a4_dir"] = str(output_dir / f"_merged_{merged.plan.cols}x{merged.plan.rows}")
        result["merged_a4_layout"] = f"{merged.plan.cols}x{merged.plan.rows}"
        result["merged_a4_pages"] = int(merged.plan.page_count)
        if merged.warning:
            result["merged_a4_warning"] = merged.warning
        self._append_log(
            "画像マージ完了: "
            f"pages={merged.plan.page_count} layout={merged.plan.cols}x{merged.plan.rows} "
            f"outputs={len(merged.paths)}"
        )
        if merged.warning:
            self._append_log(f"[WARN] {merged.warning}")
        return result

    def _on_merge_a4_clicked(self) -> None:
        if self._is_running:
            messagebox.showwarning("実行中", "処理実行中は画像マージを開始できません。")
            return
        png_paths = self._resolve_latest_plot_ref_png_paths()
        if not png_paths:
            messagebox.showerror("入力エラー", "plots_reference のPNGが見つかりません。先にグラフを出力してください。")
            return
        output_dir = png_paths[0].parent
        try:
            merged = self._merge_plot_ref_pngs_to_a4(png_paths=png_paths, output_dir=output_dir)
        except Exception as exc:  # noqa: BLE001
            self._append_log(f"[ERROR] 画像マージ失敗: {exc}")
            messagebox.showerror("画像マージ失敗", str(exc))
            return
        self._append_log(
            "画像マージ(手動): "
            f"inputs={len(png_paths)} outputs={len(merged.paths)} "
            f"layout={merged.plan.cols}x{merged.plan.rows} pages={merged.plan.page_count}"
        )
        if merged.warning:
            self._append_log(f"[WARN] {merged.warning}")
        message = (
            "画像マージが完了しました。\n\n"
            f"入力PNG: {len(png_paths)}\n"
            f"出力ページ: {len(merged.paths)}\n"
            f"レイアウト: {merged.plan.cols}x{merged.plan.rows}\n"
            f"出力先: {output_dir / f'_merged_{merged.plan.cols}x{merged.plan.rows}'}"
        )
        if merged.warning:
            message += f"\n\n警告: {merged.warning}"
        messagebox.showinfo("画像マージ完了", message)

    def _on_run_clicked(self) -> None:
        if self._is_running:
            return
        mode = self.run_mode_var.get().strip()
        if mode == "Excelデータ":
            try:
                excel_config = self._validate_excel_for_run()
            except ValueError as exc:
                messagebox.showerror("入力エラー", str(exc))
                return
            if not self._confirm_excel_run(excel_config):
                self._append_log("実行をキャンセルしました（イベント確認）。")
                self._set_status("待機中")
                return
            policy = self._resolve_conflict_policy_for_excel(excel_config)
            if policy is None:
                self._append_log("実行をキャンセルしました（出力ファイル重複）。")
                self._set_status("待機中")
                return
            excel_config = replace(excel_config, on_conflict=policy)
            self._append_log(f"ファイル衝突時の挙動: {policy}")
            self._is_running = True
            self._set_status("実行中")
            self._update_graph_span_label()
            self._append_log(
                f"実行開始(Excel): events={len(excel_config.selected_events)} "
                f"inputs={len(excel_config.input_excels)} "
                f"span={excel_config.graph_span} graph_kinds={list(excel_config.ref_graph_kinds)}"
            )
            _save_state(self._collect_state_payload())

            def excel_worker() -> None:
                result: dict[str, object] | None = None
                error_log_text: str | None = None
                error_dialog_text: str | None = None
                try:
                    result = run_excel_mode(excel_config)
                    jobs_raw = result.get("intermediate_jobs", []) if isinstance(result, dict) else []
                    if isinstance(jobs_raw, list) and jobs_raw:
                        out_json = self._write_intermediate_json(
                            output_root=excel_config.output_root,
                            jobs=[job for job in jobs_raw if isinstance(job, dict)],
                            filename="_intermediate_excel.json",
                            source_mode="excel",
                        )
                        result["intermediate_json_path"] = str(out_json)
                except ZipFlowError as exc:
                    error_log_text = f"[ERROR] {exc}"
                    error_dialog_text = str(exc)
                except Exception as exc:  # noqa: BLE001
                    error_log_text = f"[ERROR] 想定外エラー: {exc}"
                    error_dialog_text = f"想定外エラーが発生しました。\n{exc}"

                def done() -> None:
                    self._is_running = False
                    self._update_graph_span_label()
                    if error_dialog_text is not None:
                        self._set_status("失敗", is_error=True)
                        self._append_log(error_log_text or f"[ERROR] {error_dialog_text}")
                        messagebox.showerror("実行失敗", error_dialog_text)
                        return
                    result_data = result
                    assert result_data is not None
                    plot_ref_png_paths = self._extract_plot_ref_png_paths_from_result(result_data)
                    self._last_plot_ref_png_paths = plot_ref_png_paths
                    if self.merge_a4_enabled_var.get() and plot_ref_png_paths:
                        try:
                            result_data = self._run_a4_merge_and_attach(
                                result=result_data,
                                png_paths=plot_ref_png_paths,
                                output_dir=plot_ref_png_paths[0].parent,
                            )
                        except Exception as exc:  # noqa: BLE001
                            self._append_log(f"[ERROR] 画像マージ失敗(自動): {exc}")
                    self._last_result = result_data
                    self._set_status("完了")
                    self._append_log("実行完了")
                    self._set_summary(self._format_summary(result_data))
                    if result_data.get("intermediate_json_path"):
                        self._append_log(f"中間JSON出力(Excel): {result_data['intermediate_json_path']}")
                    messagebox.showinfo("実行完了", self._build_completion_message(result_data, mode="Excelデータ"))

                self.root.after(0, done)

            threading.Thread(target=excel_worker, daemon=True).start()
            return

        try:
            configs, day_count = self._build_rain_run_configs()
        except ValueError as exc:
            messagebox.showerror("入力エラー", str(exc))
            return
        configs, style_snapshot_dir = self._freeze_style_profile_for_run(configs)
        if style_snapshot_dir is not None:
            self._append_log(f"スタイル設定を実行用スナップショットに固定: {style_snapshot_dir}")
        policy = self._resolve_conflict_policy_for_plot_ref_batch(configs)
        if policy is None:
            self._append_log("実行をキャンセルしました（出力ファイル重複）。")
            self._set_status("待機中")
            return
        configs_with_policy = [replace(cfg, on_conflict=policy) for cfg in configs]
        if configs_with_policy and "plots_ref" in configs_with_policy[0].output_kinds:
            self._append_log(f"ファイル衝突時の挙動: {configs_with_policy[0].on_conflict}")

        self._is_running = True
        self._set_status("実行中")
        self._update_graph_span_label()
        if len(configs_with_policy) == 1:
            cfg = configs_with_policy[0]
            self._append_log(
                f"実行開始: period={cfg.start_date:%Y-%m-%d}..{cfg.end_date:%Y-%m-%d} ({day_count}日) "
                f"regions={list(cfg.region_keys)} outputs={list(cfg.output_kinds)}"
            )
        else:
            self._append_log(
                f"実行開始: 対象日{len(configs_with_policy)}件 / {self.rain_panel.get_window_mode_label()} "
                f"({day_count}日窓) regions={list(configs_with_policy[0].region_keys)} "
                f"outputs={list(configs_with_policy[0].output_kinds)}"
            )
        _save_state(self._collect_state_payload())

        def worker() -> None:
            result: dict[str, object] | None = None
            error_text: str | None = None
            collected_plot_ref_png_paths: list[Path] = []

            def emit_log(message: str) -> None:
                self.root.after(0, lambda m=message: self._append_log(m))

            try:
                zip_windows_cache: dict[Path, list] = {}
                regions_cache: dict[Path, list] = {}
                for cfg in configs_with_policy:
                    zip_key = cfg.input_zipdir.resolve()
                    if zip_key not in zip_windows_cache:
                        zip_windows_cache[zip_key] = list_zip_windows(input_zipdir=cfg.input_zipdir)
                    polygon_key = cfg.polygon_dir.resolve()
                    if polygon_key not in regions_cache:
                        from ..regions import load_region_specs

                        regions_cache[polygon_key] = load_region_specs(cfg.polygon_dir)
                emit_log(
                    f"事前準備: ZIP期間一覧 {len(zip_windows_cache)}件, 流域定義 {len(regions_cache)}件 を共有化"
                )

                if len(configs_with_policy) == 1:
                    cfg = configs_with_policy[0]
                    from ..application import run_zipflow

                    emit_log(
                        "処理中: ZIP選定・ラスタ切出し・集計を実行中 "
                        f"({cfg.start_date:%Y-%m-%d}..{cfg.end_date:%Y-%m-%d})"
                    )
                    result = run_zipflow(
                        cfg,
                        prelisted_windows=zip_windows_cache[cfg.input_zipdir.resolve()],
                        preloaded_regions=regions_cache[cfg.polygon_dir.resolve()],
                        collect_metric_frames="plots_ref" in cfg.output_kinds,
                    )
                    collected_plot_ref_png_paths = self._extract_plot_ref_png_paths_from_result(result)
                    if "plots_ref" in cfg.output_kinds:
                        frame_payload_raw = result.get("plot_frames_by_region")
                        if not isinstance(frame_payload_raw, dict):
                            raise ZipFlowError("plot_frames_by_region を取得できませんでした。", exit_code=5)
                        jobs: list[dict[str, Any]] = []
                        for region_key in cfg.region_keys:
                            region_payload = frame_payload_raw.get(region_key)
                            if not isinstance(region_payload, dict):
                                continue
                            jobs.append(
                                {
                                    "base_date": cfg.base_date.strftime(_DATE_FMT),
                                    "reference_base_date": (cfg.reference_base_date or cfg.base_date).strftime(
                                        _DATE_FMT
                                    ),
                                    "region_key": region_key,
                                    "region_label": _REGION_LABELS.get(region_key, region_key),
                                    "graph_spans": list(cfg.graph_spans),
                                    "ref_graph_kinds": list(cfg.ref_graph_kinds),
                                    "observed_at_jst": region_payload.get("observed_at_jst", []),
                                    "weighted_sum_mm": region_payload.get("weighted_sum_mm", []),
                                    "weighted_mean_mm": region_payload.get("weighted_mean_mm", []),
                                }
                            )
                        out_json = self._write_intermediate_json(output_root=cfg.output_root, jobs=jobs)
                        emit_log(f"中間JSON出力: {out_json}")
                    emit_log(
                        "処理中: 集計完了 "
                        f"(zip={result.get('zip_count')} plot={result.get('plot_count')} "
                        f"csv={result.get('csv_count')}/{result.get('cell_csv_count')})"
                    )
                else:
                    agg_plot = 0
                    agg_zip = 0
                    agg_csv = 0
                    agg_cell_csv = 0
                    last_base_dir = None
                    last_log_path = None
                    total_jobs = len(configs_with_policy)
                    from ..application import run_zipflow
                    plot_jobs: list[dict[str, Any]] = []
                    intermediate_by_root: dict[Path, list[dict[str, Any]]] = {}
                    requested_plot_ref_any = False
                    generated_plot_ref_png_paths: list[Path] = []

                    for idx, cfg in enumerate(configs_with_policy, start=1):
                        emit_log(
                            f"処理中 [{idx}/{total_jobs}]: "
                            f"target={cfg.base_date:%Y-%m-%d} "
                            f"period={cfg.start_date:%Y-%m-%d}..{cfg.end_date:%Y-%m-%d}"
                        )
                        requested_outputs = set(cfg.output_kinds)
                        requested_plot_ref_any = requested_plot_ref_any or ("plots_ref" in requested_outputs)
                        effective_outputs = list(cfg.output_kinds)
                        if "plots_ref" in requested_outputs:
                            effective_outputs = [k for k in effective_outputs if k != "plots_ref"]
                        run_cfg = replace(cfg, output_kinds=tuple(effective_outputs))
                        one = run_zipflow(
                            run_cfg,
                            prelisted_windows=zip_windows_cache[cfg.input_zipdir.resolve()],
                            preloaded_regions=regions_cache[cfg.polygon_dir.resolve()],
                            collect_metric_frames="plots_ref" in requested_outputs,
                        )
                        emit_log(
                            f"処理完了 [{idx}/{total_jobs}]: "
                            f"target={cfg.base_date:%Y-%m-%d} "
                            f"zip={one.get('zip_count')} plot={one.get('plot_count')} "
                            f"csv={one.get('csv_count')}/{one.get('cell_csv_count')}"
                        )
                        agg_plot += int(cast(int, one.get("plot_count") or 0))
                        agg_zip += int(cast(int, one.get("zip_count") or 0))
                        agg_csv += int(cast(int, one.get("csv_count") or 0))
                        agg_cell_csv += int(cast(int, one.get("cell_csv_count") or 0))
                        last_base_dir = one.get("base_dir")
                        last_log_path = one.get("log_path")

                        if "plots_ref" in requested_outputs:
                            frame_payload_raw = one.get("plot_frames_by_region")
                            if not isinstance(frame_payload_raw, dict):
                                raise ZipFlowError("plot_frames_by_region を取得できませんでした。", exit_code=5)
                            root_key = (cfg.output_root / "plots_reference").resolve()
                            root_payload = intermediate_by_root.setdefault(root_key, [])
                            for region_key in cfg.region_keys:
                                region_payload = frame_payload_raw.get(region_key)
                                if not isinstance(region_payload, dict):
                                    detail = (
                                        f"region={region_key} date={cfg.base_date:%Y-%m-%d}"
                                    )
                                    raise ZipFlowError(
                                        f"中間データが不足しています: {detail}",
                                        exit_code=5,
                                    )
                                observed_at_raw = region_payload.get("observed_at_jst")
                                sum_raw = region_payload.get("weighted_sum_mm")
                                mean_raw = region_payload.get("weighted_mean_mm")
                                if (
                                    not isinstance(observed_at_raw, list)
                                    or not isinstance(sum_raw, list)
                                    or not isinstance(mean_raw, list)
                                ):
                                    raise ZipFlowError(
                                        f"中間データ形式が不正です: region={region_key} date={cfg.base_date:%Y-%m-%d}",
                                        exit_code=5,
                                    )
                                observed_at = pd.to_datetime(observed_at_raw, errors="coerce")
                                if observed_at.isna().any():
                                    detail = (
                                        f"region={region_key} date={cfg.base_date:%Y-%m-%d}"
                                    )
                                    raise ZipFlowError(
                                        f"中間JSONの observed_at_jst が不正です: {detail}",
                                        exit_code=5,
                                    )
                                plot_jobs.append(
                                    {
                                        "config": cfg,
                                        "region_key": region_key,
                                        "frame_sum": build_metric_frame(
                                            observed_at=observed_at.to_list(),
                                            weighted_sum=[
                                                float(v) if v is not None else 0.0 for v in sum_raw
                                            ],
                                        ),
                                        "frame_mean": build_metric_frame(
                                            observed_at=observed_at.to_list(),
                                            weighted_sum=[
                                                float(v) if v is not None else 0.0 for v in mean_raw
                                            ],
                                        ),
                                    }
                                )
                                root_payload.append(
                                    {
                                        "base_date": cfg.base_date.strftime(_DATE_FMT),
                                        "reference_base_date": (
                                            (cfg.reference_base_date or cfg.base_date).strftime(_DATE_FMT)
                                        ),
                                        "region_key": region_key,
                                        "region_label": _REGION_LABELS.get(region_key, region_key),
                                        "graph_spans": list(cfg.graph_spans),
                                        "ref_graph_kinds": list(cfg.ref_graph_kinds),
                                        "observed_at_jst": [str(ts) for ts in observed_at_raw],
                                        "weighted_sum_mm": [float(v) if v is not None else 0.0 for v in sum_raw],
                                        "weighted_mean_mm": [float(v) if v is not None else 0.0 for v in mean_raw],
                                    }
                                )

                    if requested_plot_ref_any and not plot_jobs:
                        raise ZipFlowError(
                            "plots_ref が要求されましたが、描画対象の中間データを構築できませんでした。",
                            exit_code=5,
                        )

                    if plot_jobs:
                        emit_log("処理中: 複数対象日の共通軸上限を算出中")
                        shared_axis_tops_by_region = self._compute_shared_axis_tops_for_batch(plot_jobs=plot_jobs)
                        emit_log("処理中: 共通軸上限でグラフ描画中")
                        style_cache: dict[Path | None, Any] = {}
                        for job in plot_jobs:
                            cfg = cast(RunConfig, job["config"])
                            region_key = cast(str, job["region_key"])
                            frame_sum = cast(pd.DataFrame, job["frame_sum"])
                            frame_mean = cast(pd.DataFrame, job["frame_mean"])
                            axis_tops = shared_axis_tops_by_region.get(region_key, {})
                            style_key = cfg.style_profile_path
                            if style_key not in style_cache:
                                style_cache[style_key] = load_style_profile(style_key)
                            generated = render_region_plots_reference(
                                frame_sum=frame_sum,
                                frame_mean=frame_mean,
                                region_key=region_key,
                                region_label=_REGION_LABELS.get(region_key, region_key),
                                output_dir=cfg.output_root / "plots_reference",
                                base_date=cfg.reference_base_date or cfg.base_date,
                                graph_spans=cfg.graph_spans,
                                ref_graph_kinds=cfg.ref_graph_kinds,
                                export_svg=cfg.export_svg,
                                on_conflict=cfg.on_conflict,
                                style=style_cache[style_key],
                                axis_tops=axis_tops,
                            )
                            agg_plot += len(generated)
                            generated_plot_ref_png_paths.extend(
                                [path for path in generated if path.suffix.lower() == ".png"]
                            )
                        for root_dir, jobs in intermediate_by_root.items():
                            out_json = self._write_intermediate_json(output_root=root_dir.parent, jobs=jobs)
                            emit_log(f"中間JSON出力: {out_json}")
                    collected_plot_ref_png_paths = generated_plot_ref_png_paths

                    if requested_plot_ref_any and agg_plot <= 0:
                        raise ZipFlowError(
                            "plots_ref が要求されましたが、グラフ出力件数が0件でした。",
                            exit_code=7,
                        )

                    result = {
                        "base_dir": last_base_dir,
                        "zip_count": agg_zip,
                        "plot_count": agg_plot,
                        "csv_count": agg_csv,
                        "cell_csv_count": agg_cell_csv,
                        "log_path": last_log_path,
                        "csv_readme_path": None,
                    }
                    if collected_plot_ref_png_paths:
                        result["plot_ref_png_paths"] = [str(path) for path in collected_plot_ref_png_paths]
            except ZipFlowError as exc:
                error_text = str(exc)
                self._append_log(f"[ERROR] {exc}")
            except Exception as exc:  # noqa: BLE001
                error_text = f"想定外エラーが発生しました。\n{exc}"
                self._append_log(f"[ERROR] 想定外エラー: {exc}")
            finally:
                if style_snapshot_dir is not None:
                    shutil.rmtree(style_snapshot_dir, ignore_errors=True)

            def done() -> None:
                self._is_running = False
                self._update_graph_span_label()
                if error_text is not None:
                    self._set_status("失敗", is_error=True)
                    messagebox.showerror("実行失敗", error_text)
                    return
                result_data = result
                assert result_data is not None
                resolved_paths = self._extract_plot_ref_png_paths_from_result(result_data)
                self._last_plot_ref_png_paths = resolved_paths
                if self.merge_a4_enabled_var.get() and resolved_paths:
                    try:
                        result_data = self._run_a4_merge_and_attach(
                            result=result_data,
                            png_paths=resolved_paths,
                            output_dir=resolved_paths[0].parent,
                        )
                    except Exception as exc:  # noqa: BLE001
                        self._append_log(f"[ERROR] 画像マージ失敗(自動): {exc}")
                self._last_result = result_data
                self._set_status("完了")
                self._append_log("実行完了")
                self._set_summary(self._format_summary(result_data))
                self._set_auto_tuner_csv()
                messagebox.showinfo("実行完了", self._build_completion_message(result_data, mode="解析雨量データ"))

            self.root.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def _freeze_style_profile_for_run(self, configs: list[RunConfig]) -> tuple[list[RunConfig], Path | None]:
        style_paths = {cfg.style_profile_path for cfg in configs if cfg.style_profile_path is not None}
        if not style_paths:
            return configs, None

        snapshot_dir = Path(tempfile.mkdtemp(prefix="uc_rainfall_style_snapshot_"))
        snapshot_map: dict[Path, Path] = {}
        try:
            for src in style_paths:
                assert src is not None
                if not src.exists():
                    continue
                dest = snapshot_dir / src.name
                dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
                snapshot_map[src] = dest

            frozen: list[RunConfig] = []
            for cfg in configs:
                src = cfg.style_profile_path
                if src is None:
                    frozen.append(cfg)
                    continue
                frozen_path = snapshot_map.get(src, src)
                frozen.append(replace(cfg, style_profile_path=frozen_path))
            return frozen, snapshot_dir
        except Exception:
            shutil.rmtree(snapshot_dir, ignore_errors=True)
            raise

    def _format_summary(self, result: dict[str, object]) -> str:
        if result.get("event_count") is not None:
            lines = [
                f"出力先: {result.get('base_dir')}",
                f"対象イベント数: {result.get('event_count')}",
                f"グラフ出力数: {result.get('plot_count')}",
            ]
            if result.get("log_path"):
                lines.append(f"ログ: {result['log_path']}")
            if result.get("intermediate_json_path"):
                lines.append(f"中間JSON: {result['intermediate_json_path']}")
            if result.get("merged_a4_count") is not None:
                lines.append(
                    "画像マージ: "
                    f"{result.get('merged_a4_count')}ページ "
                    f"(layout={result.get('merged_a4_layout')})"
                )
                if result.get("merged_a4_warning"):
                    lines.append(f"警告: {result.get('merged_a4_warning')}")
            return "\n".join(lines)
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
        if result.get("merged_a4_count") is not None:
            lines.append(
                "画像マージ: "
                f"{result.get('merged_a4_count')}ページ "
                f"(layout={result.get('merged_a4_layout')})"
            )
            if result.get("merged_a4_warning"):
                lines.append(f"警告: {result.get('merged_a4_warning')}")
        return "\n".join(lines)

    def _build_completion_message(self, result: dict[str, object], *, mode: str) -> str:
        if mode == "Excelデータ":
            lines = [
                "処理が完了しました。",
                f"対象イベント数: {result.get('event_count')}",
                f"グラフ出力数: {result.get('plot_count')}",
                f"出力先: {result.get('base_dir')}",
            ]
            if result.get("log_path"):
                lines.append(f"ログ: {result.get('log_path')}")
            if result.get("intermediate_json_path"):
                lines.append(f"中間JSON: {result.get('intermediate_json_path')}")
            if result.get("merged_a4_count") is not None:
                lines.append(
                    "画像マージ: "
                    f"{result.get('merged_a4_count')}ページ "
                    f"(layout={result.get('merged_a4_layout')})"
                )
                if result.get("merged_a4_warning"):
                    lines.append(f"警告: {result.get('merged_a4_warning')}")
            return "\n".join(lines)
        lines = [
            "処理が完了しました。",
            f"採用ZIP数: {result.get('zip_count')}",
            f"グラフ出力数: {result.get('plot_count')}",
            f"時系列CSV数: {result.get('csv_count')}",
            f"セルCSV数: {result.get('cell_csv_count')}",
            f"出力先: {result.get('base_dir')}",
        ]
        if result.get("log_path"):
            lines.append(f"ログ: {result.get('log_path')}")
        if result.get("merged_a4_count") is not None:
            lines.append(
                "画像マージ: "
                f"{result.get('merged_a4_count')}ページ "
                f"(layout={result.get('merged_a4_layout')})"
            )
            if result.get("merged_a4_warning"):
                lines.append(f"警告: {result.get('merged_a4_warning')}")
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
        if self.run_mode_var.get().strip() == "Excelデータ":
            return
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
        mode = self.run_mode_var.get().strip()
        if mode == "Excelデータ":
            try:
                frame = self.excel_panel.build_preview_frame(self.input_excel_var.get().strip())
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("起動エラー", f"Excelプレビューを読み込めませんでした: {exc}")
                self._append_log(f"[ERROR] グラフスタイル調整のExcelプレビュー読込失敗: {exc}")
                return
            if frame is None or frame.empty:
                self._append_log("Excel候補が未選択のためテンプレートでスタイル調整を起動します。")
                frame = None
            try:
                tuner_input = StyleTunerInput(
                    source_kind="excel" if frame is not None else "template",
                    frame=frame,
                    value_kind=self._resolve_primary_value_kind(),
                    preview_span=self.excel_panel.get_preview_span(),
                    title_template="流域平均雨量（{start} - {end}）",
                )
                launch_style_tuner(
                    tuner_input=tuner_input,
                    input_csv=None,
                    value_kind=tuner_input.value_kind,
                    title=tuner_input.title_template,
                    sample_mode="synthetic",
                    profile_path=default_style_profile_path(),
                    preview_span=tuner_input.preview_span,
                    master=self.root,
                )
                self._append_log("グラフスタイル調整を起動しました。")
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("起動エラー", f"グラフスタイル調整を起動できませんでした: {exc}")
            return

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
            tuner_input = StyleTunerInput(
                source_kind="csv" if input_csv is not None else "template",
                frame=None,
                value_kind=self._resolve_primary_value_kind(),
                preview_span=self._resolve_current_graph_span(),
                title_template="流域平均雨量（{start} - {end}）",
            )
            launch_style_tuner(
                tuner_input=tuner_input,
                input_csv=input_csv,
                value_kind=tuner_input.value_kind,
                title=tuner_input.title_template,
                sample_mode="synthetic",
                profile_path=profile_path,
                preview_span=tuner_input.preview_span,
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
            _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = _SCREENSHOT_DIR / f"zipflow_gui_{stamp}.png"
            self._capture_window(out_path)
            self._append_log(f"画面スクリーンショットを保存しました: {out_path}")
            self._set_status("スクリーンショット保存完了")
        except Exception:
            messagebox.showerror(
                "スクリーンショット失敗",
                "Pillow(ImageGrab)が利用できません。`uv add pillow` 後に再実行してください。",
            )
        return "break"

    def _capture_window(self, out_path: Path) -> None:
        from PIL import ImageGrab

        self.root.update_idletasks()
        x = self.root.winfo_rootx()
        y = self.root.winfo_rooty()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        if w <= 0 or h <= 0:
            raise ValueError("ウィンドウサイズが無効です。")
        image = ImageGrab.grab(bbox=(x, y, x + w, y + h))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(out_path)

    def _run_startup_test(self) -> None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        shot_path = _GUI_TEST_DIR / f"startup_{stamp}.png"
        report_path = _GUI_TEST_DIR / f"startup_{stamp}.json"
        required_widgets = {
            "run_button": self.run_button,
            "status_label": self.status_label,
            "log_text": self.log_text,
            "summary_text": self.summary_text,
        }
        missing = [name for name, widget in required_widgets.items() if widget is None or not widget.winfo_exists()]
        screenshot_error: str | None = None
        try:
            self._capture_window(shot_path)
        except Exception as exc:  # noqa: BLE001
            screenshot_error = str(exc)
        report = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ok": len(missing) == 0 and screenshot_error is None,
            "missing_widgets": missing,
            "screenshot": str(shot_path) if screenshot_error is None else None,
            "screenshot_error": screenshot_error,
            "window_title": self.root.title(),
            "window_size": f"{self.root.winfo_width()}x{self.root.winfo_height()}",
        }
        _GUI_TEST_DIR.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        self._append_log(f"起動テスト結果を保存しました: {report_path}")
        if report["ok"]:
            self._set_status("起動テスト: 成功")
        else:
            self._set_status("起動テスト: 失敗", is_error=True)
        self.root.after(250, self._on_close)

    def run(self) -> None:
        self.root.mainloop()


def launch_zipflow_gui(*, dev_mode: bool | None = None) -> None:
    app = ZipFlowGui(dev_mode=dev_mode)
    app.run()


def launch_zipflow_gui_with_capture(
    *,
    auto_capture_seconds: float | None,
    auto_exit_after_capture: bool,
    test_mode: bool = False,
    dev_mode: bool | None = None,
) -> None:
    app = ZipFlowGui(
        auto_capture_seconds=auto_capture_seconds,
        auto_exit_after_capture=auto_exit_after_capture,
        test_mode=test_mode,
        dev_mode=dev_mode,
    )
    app.run()
