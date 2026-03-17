from __future__ import annotations

import argparse
import logging
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from tkinter import filedialog, ttk
from typing import Any, cast

import pandas as pd
from matplotlib.patches import Rectangle

from ..db import open_db
from ..settings_store import update_settings
from .actions import (
    add_input_files,
    apply_spatial_selected_cell,
    browse_db_path,
    browse_out_dir,
    browse_polygon_dir,
    clear_input_paths,
    clear_spatial_selection,
    handle_ingest,
    handle_init_db,
    handle_list_candidates,
    handle_plot,
    handle_render_spatial_view,
    handle_save_log,
    handle_save_screenshot,
    handle_save_test_context,
    handle_save_widget_tree,
    highlight_spatial_selected_cell,
    on_candidate_selected,
    on_spatial_canvas_click,
    populate_candidate_tree,
    render_spatial_payload,
    validate_db_path,
    validate_input_paths,
    validate_plot_times,
    validate_polygon_name,
)
from .layout import (
    build_candidate_area,
    build_input_area,
    build_layout,
    build_log_area,
    build_spatial_area,
    build_timestamp_selector,
)
from .logging_handler import GuiLogHandler
from .state import GuiState
from .test_mode import (
    build_spatial_view_meta,
    close_active_dialog,
    collect_widget_tree,
    execute_action,
    execute_canvas_point_action,
    get_treeview_meta,
    get_widget_value,
    has_overflow_hint,
    is_widget_enabled,
    on_test_mode_toggled,
    open_test_dialog,
    poll_action_requests,
    process_action_request,
    record_last_run,
    save_context_file,
    save_last_run_file,
    save_log_file,
    save_screenshot_file,
    save_widget_tree_file,
    select_tree_row,
    set_widget_value,
    show_dialog,
    show_error,
    show_info,
    update_test_summary,
    wait_until_idle,
    write_test_artifacts,
)
from .validation import (
    set_entry_validity,
    validate_datetime_inputs_inline,
    validate_db_path_inline,
    validate_input_paths_inline,
    validate_out_dir_inline,
    validate_spatial_timestamp_inline,
)

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
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        initial_width = min(1360, max(1100, int(screen_width * 0.88)))
        initial_height = min(920, max(760, int(screen_height * 0.86)))
        initial_x = max(0, (screen_width - initial_width) // 2)
        initial_y = max(0, (screen_height - initial_height) // 2)
        self.root.geometry(f"{initial_width}x{initial_height}+{initial_x}+{initial_y}")
        self.root.minsize(1100, 760)
        self.state = GuiState(self.root, test_mode_default=test_mode)
        self.db_entry: ttk.Entry
        self.input_paths_listbox: tk.Listbox
        self.polygon_dir_entry: ttk.Entry
        self.out_dir_entry: ttk.Entry
        self.ingest_dataset_entry: ttk.Entry
        self.io_validation_label: ttk.Label
        self.preferred_dataset_combo: ttk.Combobox
        self.polygon_name_combo: ttk.Combobox
        self.series_mode_combo: ttk.Combobox
        self.local_row_combo: ttk.Combobox
        self.local_col_combo: ttk.Combobox
        self.params_validation_label: ttk.Label
        self.test_mode_check: ttk.Checkbutton
        self.status_label: ttk.Label
        self.candidate_summary_label: ttk.Label
        self.candidate_tree: ttk.Treeview
        self.view_notebook: ttk.Notebook
        self.spatial_metric_combo: ttk.Combobox
        self.spatial_status_label: ttk.Label
        self.log_text: tk.Text
        self._main_buttons: list[ttk.Button] = []
        self._log_handler: GuiLogHandler | None = None
        self._candidate_items: dict[str, dict[str, Any]] = {}
        self._ui_queue: Queue[tuple[Any, ...]] = Queue()
        self._busy_action: str | None = None
        self._active_dialog: tk.Toplevel | None = None
        self._spatial_payload: dict[str, Any] | None = None
        self.spatial_figure: Any = cast(Any, None)
        self.spatial_ax: Any = cast(Any, None)
        self.spatial_canvas: Any = cast(Any, None)
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
        build_layout(self)

    def _build_input_area(self, frame: ttk.Frame) -> None:
        """入力エリアを組み立てる。"""
        build_input_area(self, frame)

    def _build_candidate_area(self, frame: ttk.Frame) -> None:
        """候補セルテーブルと面ビューを構築する。"""
        build_candidate_area(self, frame)

    def _build_spatial_area(self, frame: ttk.Frame) -> None:
        """面ビュータブを構築する。"""
        build_spatial_area(self, frame)

    def _build_log_area(self, frame: ttk.LabelFrame) -> None:
        """ログエリアを構築する。"""
        build_log_area(self, frame)

    def _build_timestamp_selector(
        self,
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
        build_timestamp_selector(
            self,
            parent,
            row=row,
            label_text=label_text,
            prefix=prefix,
            year_var=year_var,
            month_var=month_var,
            day_var=day_var,
            time_var=time_var,
            on_change=on_change,
        )

    def _register_widget(self, widget_id: str, widget: tk.Misc, role: str, display_name: str) -> None:
        """AI テスト向けの widget registry へ登録する。"""
        self.state.widget_registry[widget_id] = {
            "widget": widget,
            "role": role,
            "display_name": display_name,
        }

    def _apply_cached_input_paths(self) -> None:
        """設定キャッシュ上の入力パスを一覧へ反映する。"""
        self.state.input_paths = list(self.state.input_paths)
        display_items = [_display_input_path(path) for path in self.state.input_paths]
        self._set_listbox_items(self.input_paths_listbox, display_items)

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
                        polygon_rows = conn.execute(
                            "SELECT polygon_name FROM polygons ORDER BY polygon_name"
                        ).fetchall()
                        dataset_rows = conn.execute("SELECT dataset_id FROM datasets ORDER BY dataset_id").fetchall()
                    polygon_values = [str(row[0]) for row in polygon_rows]
                    dataset_values = [str(row[0]) for row in dataset_rows]
                    self._db_metadata_cache[db_path] = (polygon_values, dataset_values)
                except Exception as exc:
                    LOGGER.warning("DB メタデータの読込に失敗しました: %s", exc)
        self.polygon_name_combo.configure(values=polygon_values)
        self.preferred_dataset_combo.configure(values=[ALL_DATASETS_LABEL] + dataset_values)
        polygon_name = self.state.polygon_name_var.get().strip()
        if polygon_name and polygon_name not in polygon_values:
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
        timestamps: list[Any] = []
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
                    timestamps = [pd.Timestamp(str(row[0])) for row in rows if row[0] is not None]
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
        row_series = self.state.candidate_frame["polygon_local_row"].dropna().tolist()
        col_series = self.state.candidate_frame["polygon_local_col"].dropna().tolist()
        row_values = sorted({str(int(value)) for value in row_series})
        col_values = sorted({str(int(value)) for value in col_series})
        self.local_row_combo.configure(values=row_values)
        self.local_col_combo.configure(values=col_values)
        if self.state.local_row_var.get().strip() and self.state.local_row_var.get().strip() not in row_values:
            self.state.local_row_var.set("")
        if self.state.local_col_var.get().strip() and self.state.local_col_var.get().strip() not in col_values:
            self.state.local_col_var.set("")

    def _get_timestamp_widgets(self, prefix: str) -> tuple[ttk.Combobox, ttk.Combobox, ttk.Combobox, ttk.Combobox]:
        """年 / 月 / 日 / 時刻の Combobox 群を取得する。"""
        return (
            getattr(self, f"{prefix}_year_combo"),
            getattr(self, f"{prefix}_month_combo"),
            getattr(self, f"{prefix}_day_combo"),
            getattr(self, f"{prefix}_time_combo"),
        )

    def _set_entry_validity(self, widget: tk.Widget, *, valid: bool) -> None:
        """簡易な入力妥当性表示を反映する。"""
        set_entry_validity(self, widget, valid=valid)

    def _validate_db_path_inline(self) -> bool:
        """DB パスの軽い事前検証を行う。"""
        return validate_db_path_inline(self)

    def _validate_input_paths_inline(self) -> bool:
        """入力パス欄の存在チェックを行う。"""
        return validate_input_paths_inline(self)

    def _validate_out_dir_inline(self) -> bool:
        """出力先フォルダの軽い検証を行う。"""
        return validate_out_dir_inline(self)

    def _validate_datetime_inputs_inline(self) -> bool:
        """日時入力の整形式チェックを行う。"""
        return validate_datetime_inputs_inline(self)

    def _validate_spatial_timestamp_inline(self) -> bool:
        """面ビュー時刻の整形式チェックを行う。"""
        return validate_spatial_timestamp_inline(self)

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
        update_test_summary(self)

    def _collect_widget_tree(self) -> dict[str, Any]:
        """登録済み widget の機械可読スナップショットを構築する。"""
        return collect_widget_tree(self)

    def _build_spatial_view_meta(self) -> dict[str, Any]:
        """面ビューの現在状態を返す。"""
        return build_spatial_view_meta(self)

    def _has_overflow_hint(self, geometry: dict[str, Any], requested: dict[str, Any]) -> bool:
        """要求サイズより実サイズが小さい場合のヒントを返す。"""
        return has_overflow_hint(self, geometry, requested)

    def _get_treeview_meta(self, widget: ttk.Treeview) -> dict[str, Any]:
        """Treeview の列情報と可視行情報を返す。"""
        return get_treeview_meta(self, widget)

    def _save_context(self) -> Path:
        """現在状態スナップショットを保存する。"""
        return save_context_file(self)

    def _save_widget_tree(self) -> Path:
        """widget tree を保存する。"""
        return save_widget_tree_file(self)

    def _save_log(self) -> Path:
        """ログ内容を保存する。"""
        return save_log_file(self)

    def _save_last_run(self) -> Path | None:
        """直近処理サマリを保存する。"""
        return save_last_run_file(self)

    def _save_screenshot(self) -> Path | None:
        """GUI スクリーンショットを保存する。"""
        return save_screenshot_file(self)

    def _write_test_artifacts(self) -> None:
        """テスト用アーティファクトをまとめて更新する。"""
        write_test_artifacts(self)

    def _record_last_run(
        self,
        *,
        action: str,
        success: bool,
        outputs: list[str] | None = None,
        error: str | None = None,
    ) -> None:
        """直近処理サマリを内部保持し、保存する。"""
        record_last_run(self, action=action, success=success, outputs=outputs, error=error)

    def _show_error(self, message: str, *, detail: str | None = None) -> None:
        """ユーザー向けエラーダイアログを出す。"""
        show_error(self, message, detail=detail)

    def _show_info(self, message: str) -> None:
        """情報ダイアログを出す。"""
        show_info(self, message)

    def _show_dialog(self, title: str, message: str, *, level: str) -> None:
        """通常時は messagebox、テストモード時は操作可能な Toplevel を出す。"""
        show_dialog(self, title, message, level=level)

    def _open_test_dialog(self, title: str, message: str, *, level: str) -> None:
        """AI テストモード用の操作可能なダイアログを表示する。"""
        open_test_dialog(self, title, message, level=level)

    def _close_active_dialog(self) -> None:
        """現在開いているテストモード用ダイアログを閉じる。"""
        close_active_dialog(self)

    def _browse_db_path(self) -> None:
        """DB 保存先ファイルを選択する。"""
        browse_db_path(self)

    def _browse_polygon_dir(self) -> None:
        """ポリゴンフォルダを選択する。"""
        browse_polygon_dir(self)

    def _browse_out_dir(self) -> None:
        """出力先フォルダを選択する。"""
        browse_out_dir(self)

    def _add_input_files(self) -> None:
        """ZIP ファイルを追加入力する。"""
        add_input_files(self)

    def _add_input_dir(self) -> None:
        """展開済みフォルダを追加入力する。"""
        path = filedialog.askdirectory(title="取り込み対象フォルダを選択")
        if path:
            self._merge_input_paths([path])

    def _clear_input_paths(self) -> None:
        """入力パス一覧をクリアする。"""
        clear_input_paths(self)

    def _validate_db_path(self) -> str:
        """DB パス必須チェックを行う。"""
        return validate_db_path(self)

    def _validate_polygon_name(self) -> str:
        """流域名必須チェックを行う。"""
        return validate_polygon_name(self)

    def _validate_plot_times(self) -> tuple[datetime, datetime]:
        """表示期間の入力を検証する。"""
        return validate_plot_times(self)

    def _validate_input_paths(self) -> list[str]:
        """取り込み対象の存在チェックを行う。"""
        return validate_input_paths(self)

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
        populate_candidate_tree(self, frame)

    def _render_spatial_payload(self, payload: dict[str, Any]) -> None:
        """面ビュー描画を実行する。"""
        render_spatial_payload(self, payload)

    def _highlight_spatial_selected_cell(self) -> None:
        """現在の selected_cell を面ビュー上で強調する。"""
        highlight_spatial_selected_cell(self)

    def _clear_spatial_selection(self) -> None:
        """面ビュー上の選択セルを解除する。"""
        clear_spatial_selection(self)

    def _on_spatial_canvas_click(self, event) -> None:
        """面ビュークリックでセル選択を反映する。"""
        on_spatial_canvas_click(self, event)

    def _apply_spatial_selected_cell(self, local_row: int, local_col: int) -> None:
        """面ビューの選択セルを入力欄へ反映する。"""
        apply_spatial_selected_cell(self, local_row, local_col)

    def _on_candidate_selected(self, _event: tk.Event[tk.Widget] | None = None) -> None:
        """候補セル選択を流域内行列へ反映する。"""
        on_candidate_selected(self, _event)

    def _handle_render_spatial_view(self) -> None:
        """面的可視化ビューを描画する。"""
        handle_render_spatial_view(self)

    def _handle_init_db(self) -> None:
        """DB 初期化を実行する。"""
        handle_init_db(self)

    def _handle_ingest(self) -> None:
        """取り込みを実行する。"""
        handle_ingest(self)

    def _handle_list_candidates(self) -> None:
        """候補セル一覧を更新する。"""
        handle_list_candidates(self)

    def _handle_plot(self) -> None:
        """イベントグラフを出力する。"""
        handle_plot(self)

    def _handle_save_test_context(self) -> None:
        """現在状態を JSON として保存する。"""
        handle_save_test_context(self)

    def _handle_save_widget_tree(self) -> None:
        """widget tree を保存する。"""
        handle_save_widget_tree(self)

    def _handle_save_screenshot(self) -> None:
        """画面を保存する。"""
        handle_save_screenshot(self)

    def _handle_save_log(self) -> None:
        """ログをテキストへ保存する。"""
        handle_save_log(self)

    def _on_test_mode_toggled(self) -> None:
        """テストモード切替時の処理。"""
        on_test_mode_toggled(self)

    def _poll_action_requests(self) -> None:
        """AI テストモードの操作要求ファイルを監視する。"""
        poll_action_requests(self)

    def _process_action_request(self, request: dict[str, Any]) -> None:
        """操作要求を解釈して GUI へ反映する。"""
        process_action_request(self, request)

    def _execute_action(self, action: dict[str, Any]) -> dict[str, Any]:
        """単一アクションを実行する。"""
        return execute_action(self, action)

    def _wait_until_idle(self, *, timeout_ms: int) -> None:
        """バックグラウンド処理完了まで待つ。"""
        wait_until_idle(self, timeout_ms=timeout_ms)

    def _set_widget_value(self, widget: tk.Widget, value: Any) -> None:
        """Entry / Text / Combobox / Checkbutton へ値を設定する。"""
        set_widget_value(self, widget, value)

    def _select_tree_row(self, widget: tk.Widget, action: dict[str, Any]) -> None:
        """Treeview で行選択を行う。"""
        select_tree_row(self, widget, action)

    def _execute_canvas_point_action(self, widget: tk.Widget, action: dict[str, Any]) -> None:
        """面ビュー canvas に対するテスト用セル選択操作を行う。"""
        execute_canvas_point_action(self, widget, action)

    def _is_widget_enabled(self, widget: tk.Widget) -> bool:
        """widget の有効状態を返す。"""
        return is_widget_enabled(self, widget)

    def _get_widget_value(self, widget: tk.Widget) -> Any:
        """widget 現在値を機械可読な形で返す。"""
        return get_widget_value(self, widget)

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
