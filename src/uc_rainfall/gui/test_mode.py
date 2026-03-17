from __future__ import annotations

import logging
import subprocess
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

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

LOGGER = logging.getLogger(__name__)


def update_test_summary(app: Any) -> None:
    """現在状態サマリを内部更新する。"""
    app.state.current_summary = {
        "db_path": app.state.db_path_var.get().strip(),
        "input_paths": app._get_input_paths(),
        "polygon_dir": app.state.polygon_dir_var.get().strip(),
        "ingest_dataset_id": app.state.ingest_dataset_id_var.get().strip(),
        "preferred_dataset_id": app.state.preferred_dataset_id_var.get().strip(),
        "polygon_name": app.state.polygon_name_var.get().strip(),
        "series_mode": app.state.get_series_mode(),
        "local_row": app.state.local_row_var.get().strip(),
        "local_col": app.state.local_col_var.get().strip(),
        "view_start": app.state.view_start_var.get().strip(),
        "view_end": app.state.view_end_var.get().strip(),
        "out_dir": app.state.out_dir_var.get().strip(),
        "spatial_timestamp": app.state.spatial_timestamp_var.get().strip(),
        "spatial_metric": app.state.get_spatial_metric(),
        "test_mode": bool(app.state.test_mode_var.get()),
        "candidate_count": int(len(app.state.candidate_frame)),
        "spatial_selected_cell": None if app._spatial_payload is None else app._spatial_payload.get("selected_cell"),
    }


def build_spatial_view_meta(app: Any) -> dict[str, Any]:
    """面ビューの現在状態を返す。"""
    if app._spatial_payload is None:
        return {
            "rendered": False,
            "selected_cell": None,
            "metric": app.state.get_spatial_metric(),
            "timestamp": app.state.spatial_timestamp_var.get().strip(),
        }
    observed_at = app._spatial_payload.get("observed_at")
    observed_at_text = (
        observed_at.isoformat(timespec="seconds")
        if isinstance(observed_at, datetime)
        else app.state.spatial_timestamp_var.get().strip()
    )
    return {
        "rendered": True,
        "dataset_id": app._spatial_payload.get("dataset_id"),
        "candidate_dataset_ids": app._spatial_payload.get("candidate_dataset_ids"),
        "polygon_name": app._spatial_payload.get("polygon_name"),
        "metric": app._spatial_payload.get("metric"),
        "timestamp": observed_at_text,
        "selected_cell": app._spatial_payload.get("selected_cell"),
        "value_label": app._spatial_payload.get("value_label"),
        "cell_count": len(app._spatial_payload.get("cells", [])),
    }


def has_overflow_hint(_app: Any, geometry: dict[str, Any], requested: dict[str, Any]) -> bool:
    """要求サイズより実サイズが小さい場合のヒントを返す。"""
    width = geometry.get("width")
    height = geometry.get("height")
    req_width = requested.get("width")
    req_height = requested.get("height")
    if width is None or height is None or req_width is None or req_height is None:
        return False
    return bool(width < req_width or height < req_height)


def is_widget_enabled(_app: Any, widget: tk.Widget) -> bool:
    """widget の有効状態を返す。"""
    try:
        state = str(widget.cget("state"))
    except tk.TclError:
        return True
    return state not in {"disabled", str(tk.DISABLED)}


def get_widget_value(_app: Any, widget: tk.Widget) -> Any:
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


def get_treeview_meta(app: Any, widget: ttk.Treeview) -> dict[str, Any]:
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


def collect_widget_tree(app: Any) -> dict[str, Any]:
    """登録済み widget の機械可読スナップショットを構築する。"""
    app.root.update_idletasks()
    widgets: list[dict[str, Any]] = []
    for widget_id, info in app.state.widget_registry.items():
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
            extra["treeview"] = get_treeview_meta(app, widget)
        value = get_widget_value(app, widget)
        widgets.append(
            {
                "widget_id": widget_id,
                "role": info["role"],
                "display_name": info["display_name"],
                "class_name": widget.winfo_class() if widget.winfo_exists() else None,
                "visible": bool(widget.winfo_ismapped()) if widget.winfo_exists() else False,
                "enabled": is_widget_enabled(app, widget),
                "value": value,
                "geometry": geometry,
                "requested_geometry": requested,
                "overflow_hint": has_overflow_hint(app, geometry, requested),
                "text_length": len(str(value or "")),
                **extra,
            }
        )
    return {
        "saved_at": datetime.now(),
        "test_mode": bool(app.state.test_mode_var.get()),
        "window_geometry": {
            "width": app.root.winfo_width(),
            "height": app.root.winfo_height(),
            "requested_width": app.root.winfo_reqwidth(),
            "requested_height": app.root.winfo_reqheight(),
        },
        "spatial_view": build_spatial_view_meta(app),
        "widgets": widgets,
    }


def save_context_file(app: Any) -> Path:
    """現在状態スナップショットを保存する。"""
    update_test_summary(app)
    payload = {
        "saved_at": datetime.now(),
        "current_summary": app.state.current_summary,
        "last_run_summary": app.state.last_run_summary,
        "spatial_view": build_spatial_view_meta(app),
        "candidate_preview": app.state.candidate_frame.head(20).to_dict(orient="records")
        if not app.state.candidate_frame.empty
        else [],
    }
    return save_gui_context(payload)


def save_widget_tree_file(app: Any) -> Path:
    """widget tree を保存する。"""
    return save_widget_tree(collect_widget_tree(app))


def save_log_file(app: Any) -> Path:
    """ログ内容を保存する。"""
    return save_gui_log(app.state.log_lines)


def save_last_run_file(app: Any) -> Path | None:
    """直近処理サマリを保存する。"""
    if not app.state.last_run_summary:
        return None
    return save_last_run(app.state.last_run_summary)


def save_screenshot_file(app: Any) -> Path | None:
    """GUI スクリーンショットを保存する。"""
    path = get_last_screenshot_path()
    if app.state.test_mode_var.get():
        app.root.lift()
        app.root.attributes("-topmost", True)
    app.root.update()
    x = app.root.winfo_rootx()
    y = app.root.winfo_rooty()
    width = app.root.winfo_width()
    height = app.root.winfo_height()
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


def write_test_artifacts(app: Any) -> None:
    """テスト用アーティファクトをまとめて更新する。"""
    try:
        save_context_file(app)
        save_widget_tree_file(app)
        if app.state.test_mode_var.get():
            save_screenshot_file(app)
    except Exception as exc:
        LOGGER.warning("テスト用アーティファクト更新に失敗しました: %s", exc)


def record_last_run(
    app: Any,
    *,
    action: str,
    success: bool,
    outputs: list[str] | None = None,
    error: str | None = None,
) -> None:
    """直近処理サマリを内部保持し、保存する。"""
    app.state.last_run_summary = {
        "recorded_at": datetime.now(),
        "action": action,
        "success": success,
        "current_summary": app.state.current_summary,
        "outputs": outputs or [],
        "error": error,
    }
    save_last_run_file(app)


def show_error(app: Any, message: str, *, detail: str | None = None) -> None:
    """ユーザー向けエラーダイアログを出す。"""
    LOGGER.error("%s%s", message, f" 詳細: {detail}" if detail else "")
    body = message if detail is None else f"{message}\n\n{detail}"
    show_dialog(app, "エラー", body, level="error")


def show_info(app: Any, message: str) -> None:
    """情報ダイアログを出す。"""
    LOGGER.info(message)
    show_dialog(app, "情報", message, level="info")


def show_dialog(app: Any, title: str, message: str, *, level: str) -> None:
    """通常時は messagebox、テストモード時は操作可能な Toplevel を出す。"""
    if not app.state.test_mode_var.get():
        if level == "error":
            messagebox.showerror(title, message)
        else:
            messagebox.showinfo(title, message)
        return
    open_test_dialog(app, title, message, level=level)


def open_test_dialog(app: Any, title: str, message: str, *, level: str) -> None:
    """AI テストモード用の操作可能なダイアログを表示する。"""
    _ = level
    close_active_dialog(app)
    dialog = tk.Toplevel(app.root)
    dialog.title(title)
    dialog.transient(app.root)
    dialog.attributes("-topmost", True)
    dialog.resizable(False, False)
    dialog.geometry("+520+180")
    dialog.columnconfigure(0, weight=1)
    app._active_dialog = dialog
    app._register_widget("dialog.active.window", dialog, "dialog", title)

    header = ttk.Label(dialog, text=title)
    header.grid(row=0, column=0, sticky="w", padx=16, pady=(14, 8))
    app._register_widget("dialog.active.header", header, "label", f"{title}見出し")

    body = ttk.Label(dialog, text=message, justify="left", wraplength=520)
    body.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 12))
    app._register_widget("dialog.active.message", body, "label", f"{title}本文")

    button_frame = ttk.Frame(dialog)
    button_frame.grid(row=2, column=0, sticky="e", padx=16, pady=(0, 14))
    app._register_widget("dialog.active.buttons", button_frame, "frame", f"{title}ボタン群")
    close_button = ttk.Button(button_frame, text="閉じる", command=lambda: close_active_dialog(app))
    close_button.grid(row=0, column=0)
    app._register_widget("dialog.active.ok", close_button, "button", f"{title}閉じる")
    dialog.protocol("WM_DELETE_WINDOW", lambda: close_active_dialog(app))
    dialog.update_idletasks()


def close_active_dialog(app: Any) -> None:
    """現在開いているテストモード用ダイアログを閉じる。"""
    dialog = app._active_dialog
    if dialog is None:
        return
    for widget_id in [
        "dialog.active.ok",
        "dialog.active.buttons",
        "dialog.active.message",
        "dialog.active.header",
        "dialog.active.window",
    ]:
        app.state.widget_registry.pop(widget_id, None)
    try:
        dialog.destroy()
    finally:
        app._active_dialog = None


def on_test_mode_toggled(app: Any) -> None:
    """テストモード切替時の処理。"""
    mode = "ON" if app.state.test_mode_var.get() else "OFF"
    LOGGER.info("テストモードを切り替えました: %s", mode)
    app.root.attributes("-topmost", bool(app.state.test_mode_var.get()))
    update_test_summary(app)


def wait_until_idle(app: Any, *, timeout_ms: int) -> None:
    """バックグラウンド処理完了まで待つ。"""
    deadline = datetime.now().timestamp() + timeout_ms / 1000.0
    while app._busy_action is not None:
        app.root.update()
        if datetime.now().timestamp() > deadline:
            raise TimeoutError(f"タイムアウトしました: busy_action={app._busy_action}")


def set_widget_value(app: Any, widget: tk.Widget, value: Any) -> None:
    """Entry / Text / Combobox / Checkbutton へ値を設定する。"""
    if isinstance(widget, tk.Text):
        app._set_text_widget(widget, str(value))
        app._refresh_control_states()
        return
    if isinstance(widget, tk.Listbox):
        items = value if isinstance(value, list) else [str(value)]
        app._set_listbox_items(widget, [str(item) for item in items])
        app._refresh_control_states()
        app._validate_input_paths_inline()
        return
    if isinstance(widget, ttk.Combobox):
        widget.set(str(value))
        app._refresh_control_states()
        if widget is app.polygon_name_combo:
            app._on_polygon_name_changed()
        if widget is app.spatial_metric_combo:
            app._update_test_summary()
        return
    if isinstance(widget, ttk.Entry):
        widget.delete(0, "end")
        widget.insert(0, str(value))
        app._refresh_control_states()
        if widget is app.db_entry:
            app._on_db_path_changed()
        elif widget is app.out_dir_entry:
            app._validate_out_dir_inline()
        return
    if widget is app.test_mode_check:
        app.state.test_mode_var.set(bool(value))
        on_test_mode_toggled(app)
        return
    raise ValueError(f"値設定に対応していない widget です: {widget!r}")


def select_tree_row(app: Any, widget: tk.Widget, action: dict[str, Any]) -> None:
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
            row = app._candidate_items.get(item_id, {})
            if all(str(row.get(key)) == str(value) for key, value in criteria.items()):
                target_item = item_id
                break
        if target_item is None:
            raise ValueError("指定条件に一致する行が見つかりません。")
    else:
        raise ValueError("row_index または criteria が必要です。")
    widget.selection_set(target_item)
    widget.focus(target_item)
    app._on_candidate_selected()


def execute_canvas_point_action(app: Any, widget: tk.Widget, action: dict[str, Any]) -> None:
    """面ビュー canvas に対するテスト用セル選択操作を行う。"""
    if widget is not app.spatial_canvas.get_tk_widget():
        raise ValueError("click_canvas_point は面ビュー canvas 専用です。")
    if app._spatial_payload is None:
        raise ValueError("面ビューがまだ描画されていません。")
    if "polygon_local_row" in action and "polygon_local_col" in action:
        app._apply_spatial_selected_cell(int(action["polygon_local_row"]), int(action["polygon_local_col"]))
        return
    if "xdata" in action and "ydata" in action:
        xdata = float(action["xdata"])
        ydata = float(action["ydata"])
        for _, info in app._spatial_rectangles:
            if float(info["minx"]) <= xdata <= float(info["maxx"]) and float(info["miny"]) <= ydata <= float(
                info["maxy"]
            ):
                app._apply_spatial_selected_cell(
                    int(info["polygon_local_row"]),
                    int(info["polygon_local_col"]),
                )
                return
        raise ValueError("指定座標に一致するセルが見つかりません。")
    raise ValueError("polygon_local_row/local_col または xdata/ydata が必要です。")


def execute_action(app: Any, action: dict[str, Any]) -> dict[str, Any]:
    """単一アクションを実行する。"""
    widget_id = str(action.get("widget_id", "")).strip()
    action_name = str(action.get("action", "")).strip()
    if not action_name:
        return {"success": False, "error": "action が必要です。"}
    if action_name == "wait_until_idle":
        try:
            timeout_ms = int(action.get("timeout_ms", 10000))
            wait_until_idle(app, timeout_ms=timeout_ms)
            LOGGER.info("テストモード操作: action=%s timeout_ms=%s", action_name, timeout_ms)
            return {"success": True, "widget_id": widget_id or "window.root", "action": action_name}
        except Exception as exc:
            LOGGER.error("テストモード操作に失敗しました: action=%s detail=%s", action_name, exc)
            return {
                "success": False,
                "widget_id": widget_id or "window.root",
                "action": action_name,
                "error": str(exc),
            }
    if not widget_id:
        return {"success": False, "error": "widget_id と action が必要です。"}
    info = app.state.widget_registry.get(widget_id)
    if info is None:
        return {"success": False, "error": f"未知の widget_id です: {widget_id}"}
    widget = info["widget"]
    try:
        if action_name in {"click", "invoke"}:
            if not hasattr(widget, "invoke"):
                raise ValueError(f"invoke 非対応 widget です: {widget_id}")
            widget.invoke()
        elif action_name == "render_spatial_view":
            app._handle_render_spatial_view()
        elif action_name in {"set_text", "select"}:
            set_widget_value(app, widget, action.get("value", ""))
        elif action_name == "focus":
            widget.focus_force()
        elif action_name == "select_tree_row":
            select_tree_row(app, widget, action)
        elif action_name == "click_canvas_point":
            execute_canvas_point_action(app, widget, action)
        else:
            raise ValueError(f"未知の操作種別です: {action_name}")
        app.root.update()
        LOGGER.info("テストモード操作: action=%s widget_id=%s", action_name, widget_id)
        return {"success": True, "widget_id": widget_id, "action": action_name}
    except Exception as exc:
        LOGGER.error(
            "テストモード操作に失敗しました: action=%s widget_id=%s detail=%s",
            action_name,
            widget_id,
            exc,
        )
        return {"success": False, "widget_id": widget_id, "action": action_name, "error": str(exc)}


def process_action_request(app: Any, request: dict[str, Any]) -> None:
    """操作要求を解釈して GUI へ反映する。"""
    request_id = str(request.get("request_id", datetime.now().isoformat()))
    if request_id == app.state.last_processed_request_id:
        return
    app.state.last_processed_request_id = request_id
    actions = request.get("actions")
    if not isinstance(actions, list):
        actions = [request]
    results: list[dict[str, Any]] = []
    for action in actions:
        result = execute_action(app, action)
        results.append(result)
        if not result["success"]:
            break
    screenshot_path = save_screenshot_file(app)
    context_path = save_context_file(app)
    widget_tree_path = save_widget_tree_file(app)
    save_log_file(app)
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


def poll_action_requests(app: Any) -> None:
    """AI テストモードの操作要求ファイルを監視する。"""
    try:
        if app.state.test_mode_var.get():
            request = load_action_request()
            if request is not None:
                process_action_request(app, request)
                clear_action_request()
    except Exception as exc:
        LOGGER.exception("テストモードの操作要求処理に失敗しました: %s", exc)
    finally:
        app.root.after(350, app._poll_action_requests)
