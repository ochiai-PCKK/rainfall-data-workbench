from __future__ import annotations

import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk
from typing import Any


def _parse_datetime(value: str) -> datetime:
    """`YYYY-MM-DDTHH:MM:SS` 形式の文字列を解釈する。"""
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")


def set_entry_validity(app: Any, widget: tk.Widget, *, valid: bool) -> None:
    """簡易な入力妥当性表示を反映する。"""
    color = "#b00020" if not valid else "#888888"
    if isinstance(widget, (tk.Text, tk.Listbox)):
        widget.configure(highlightthickness=1, highlightbackground=color, highlightcolor=color)
        return
    if isinstance(widget, ttk.Widget):
        widget.state(["!invalid"] if valid else ["invalid"])


def validate_db_path_inline(app: Any) -> bool:
    """DB パスの軽い事前検証を行う。"""
    db_path = app.state.db_path_var.get().strip()
    if not db_path:
        app.io_validation_label.configure(text="データベース保存先を指定してください。")
        set_entry_validity(app, app.db_entry, valid=False)
        return False
    app.io_validation_label.configure(
        text="" if Path(db_path).exists() else "未作成の DB です。初期化または既存 DB 指定が必要です。"
    )
    set_entry_validity(app, app.db_entry, valid=True)
    return True


def validate_input_paths_inline(app: Any) -> bool:
    """入力パス欄の存在チェックを行う。"""
    paths = app._get_input_paths()
    if not paths:
        set_entry_validity(app, app.input_paths_listbox, valid=True)
        return True
    missing = [path for path in paths if not Path(path).exists()]
    if missing:
        app.io_validation_label.configure(text=f"取り込み対象が見つかりません: {missing[0]}")
        set_entry_validity(app, app.input_paths_listbox, valid=False)
        return False
    set_entry_validity(app, app.input_paths_listbox, valid=True)
    if "見つかりません" in app.io_validation_label.cget("text"):
        app.io_validation_label.configure(text="")
    return True


def validate_out_dir_inline(app: Any) -> bool:
    """出力先フォルダの軽い検証を行う。"""
    out_dir = app.state.out_dir_var.get().strip()
    if not out_dir:
        set_entry_validity(app, app.out_dir_entry, valid=True)
        return True
    parent = Path(out_dir).parent
    valid = parent.exists()
    set_entry_validity(app, app.out_dir_entry, valid=valid)
    if not valid:
        app.io_validation_label.configure(text=f"出力先の親フォルダが存在しません: {parent}")
    elif "出力先" in app.io_validation_label.cget("text"):
        app.io_validation_label.configure(text="")
    return valid


def validate_datetime_inputs_inline(app: Any) -> bool:
    """日時入力の整形式チェックを行う。"""
    start_raw = app.state.view_start_var.get().strip()
    end_raw = app.state.view_end_var.get().strip()
    ok = True
    for widgets, raw in (
        (app._get_timestamp_widgets("view_start"), start_raw),
        (app._get_timestamp_widgets("view_end"), end_raw),
    ):
        if not raw:
            for widget in widgets:
                set_entry_validity(app, widget, valid=True)
            continue
        try:
            _parse_datetime(raw)
            for widget in widgets:
                set_entry_validity(app, widget, valid=True)
        except Exception:
            for widget in widgets:
                set_entry_validity(app, widget, valid=False)
            app.params_validation_label.configure(text="日時は年・月・日・時刻をすべて選択してください。")
            ok = False
    if ok and start_raw and end_raw:
        try:
            if _parse_datetime(start_raw) > _parse_datetime(end_raw):
                app.params_validation_label.configure(text="表示開始日時は表示終了日時以前である必要があります。")
                for widget in app._get_timestamp_widgets("view_start"):
                    set_entry_validity(app, widget, valid=False)
                for widget in app._get_timestamp_widgets("view_end"):
                    set_entry_validity(app, widget, valid=False)
                return False
        except Exception:
            return False
    if ok:
        app.params_validation_label.configure(text="")
    return ok


def validate_spatial_timestamp_inline(app: Any) -> bool:
    """面ビュー時刻の整形式チェックを行う。"""
    value = app.state.spatial_timestamp_var.get().strip()
    if not value:
        app.spatial_status_label.configure(text="面ビュー時刻を指定してください。")
        for widget in app._get_timestamp_widgets("spatial"):
            set_entry_validity(app, widget, valid=False)
        return False
    try:
        _parse_datetime(value)
    except Exception:
        app.spatial_status_label.configure(text="面ビュー時刻は年・月・日・時刻をすべて選択してください。")
        for widget in app._get_timestamp_widgets("spatial"):
            set_entry_validity(app, widget, valid=False)
        return False
    for widget in app._get_timestamp_widgets("spatial"):
        set_entry_validity(app, widget, valid=True)
    return True
