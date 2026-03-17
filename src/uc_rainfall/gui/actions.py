from __future__ import annotations

import logging
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog
from typing import Any, cast

import pandas as pd
from matplotlib import cm
from matplotlib.colors import Normalize
from matplotlib.patches import Rectangle

from ..db import initialize_schema, open_db
from ..services import (
    build_spatial_view_payload,
    generate_metric_event_charts,
    ingest_uc_rainfall,
    ingest_uc_rainfall_many,
    list_candidate_cells,
)

LOGGER = logging.getLogger(__name__)


def _parse_datetime(value: str) -> datetime:
    """`YYYY-MM-DDTHH:MM:SS` 形式の文字列を解釈する。"""
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")


def browse_db_path(app: Any) -> None:
    """DB 保存先ファイルを選択する。"""
    path = filedialog.asksaveasfilename(
        title="データベース保存先を選択",
        defaultextension=".sqlite3",
        filetypes=[("SQLite", "*.sqlite3"), ("All Files", "*.*")],
    )
    if path:
        app.state.db_path_var.set(path)
        app._on_db_path_changed()


def browse_polygon_dir(app: Any) -> None:
    """ポリゴンフォルダを選択する。"""
    path = filedialog.askdirectory(title="流域ポリゴンフォルダを選択")
    if path:
        app.state.polygon_dir_var.set(path)
        app._update_test_summary()


def browse_out_dir(app: Any) -> None:
    """出力先フォルダを選択する。"""
    path = filedialog.askdirectory(title="出力先フォルダを選択")
    if path:
        app.state.out_dir_var.set(path)
        app._validate_out_dir_inline()
        app._update_test_summary()


def add_input_files(app: Any) -> None:
    """ZIP ファイルを追加入力する。"""
    paths = filedialog.askopenfilenames(
        title="取り込み対象 ZIP を選択",
        filetypes=[("ZIP", "*.zip"), ("All Files", "*.*")],
    )
    if paths:
        app._merge_input_paths(list(paths))


def clear_input_paths(app: Any) -> None:
    """入力パス一覧をクリアする。"""
    app.state.input_paths = []
    app.input_paths_listbox.delete(0, "end")
    app._refresh_control_states()


def validate_db_path(app: Any) -> str:
    """DB パス必須チェックを行う。"""
    db_path = app.state.db_path_var.get().strip()
    if not db_path:
        raise ValueError("データベース保存先を指定してください。")
    return db_path


def validate_polygon_name(app: Any) -> str:
    """流域名必須チェックを行う。"""
    polygon_name = app.state.polygon_name_var.get().strip()
    if not polygon_name:
        raise ValueError("流域名を指定してください。")
    return polygon_name


def validate_plot_times(app: Any) -> tuple[datetime, datetime]:
    """表示期間の入力を検証する。"""
    view_start_raw = app.state.view_start_var.get().strip()
    view_end_raw = app.state.view_end_var.get().strip()
    if not view_start_raw or not view_end_raw:
        raise ValueError("表示開始日時と表示終了日時を指定してください。")
    view_start = _parse_datetime(view_start_raw)
    view_end = _parse_datetime(view_end_raw)
    if view_start > view_end:
        raise ValueError("表示開始日時は表示終了日時以前である必要があります。")
    return view_start, view_end


def validate_input_paths(app: Any) -> list[str]:
    """取り込み対象の存在チェックを行う。"""
    paths = app._get_input_paths()
    if not paths:
        raise ValueError("取り込み対象を1件以上指定してください。")
    missing = [path for path in paths if not Path(path).exists()]
    if missing:
        raise ValueError(f"取り込み対象が見つかりません: {missing[0]}")
    return paths


def populate_candidate_tree(app: Any, frame: Any) -> None:
    """候補セルテーブルを再描画する。"""
    app.state.candidate_frame = frame.copy()
    app._candidate_items.clear()
    for item_id in app.candidate_tree.get_children():
        app.candidate_tree.delete(item_id)
    if frame.empty:
        app.candidate_summary_label.configure(text="候補セル 0 件")
        app._update_test_summary()
        return
    for _, row in frame.iterrows():
        item_id = app.candidate_tree.insert(
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
        app._candidate_items[item_id] = row.to_dict()
    app.candidate_summary_label.configure(text=f"候補セル {len(frame)} 件")
    app._load_candidate_cell_choices()
    app._update_test_summary()


def render_spatial_payload(app: Any, payload: dict[str, Any]) -> None:
    """面ビュー描画を実行する。"""
    app._spatial_payload = payload
    app._spatial_payload.setdefault("selected_cell", None)
    app._spatial_cell_lookup = {}
    app._spatial_rectangles = []

    fig = app.spatial_figure
    ax = app.spatial_ax
    ax.clear()
    if app._spatial_colorbar is not None:
        try:
            app._spatial_colorbar.remove()
        except Exception:
            pass
        app._spatial_colorbar = None

    cells = payload["cells"]
    values = cast(pd.Series, pd.to_numeric(cells["value"], errors="coerce"))
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
        app._spatial_cell_lookup[key] = cell_info
        app._spatial_rectangles.append((rectangle, cell_info))

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
    sm.set_array([])
    app._spatial_colorbar = fig.colorbar(sm, ax=ax, pad=0.02, fraction=0.04, label=payload["value_label"])
    fig.tight_layout()
    app.spatial_canvas.draw_idle()
    app.view_notebook.select(app.view_notebook.tabs()[-1])
    app.spatial_status_label.configure(
        text=f"dataset={payload['dataset_id']} / cell数={len(cells)} / metric={payload['metric']}"
    )
    app._highlight_spatial_selected_cell()
    app._update_test_summary()


def highlight_spatial_selected_cell(app: Any) -> None:
    """現在の selected_cell を面ビュー上で強調する。"""
    selected = None if app._spatial_payload is None else app._spatial_payload.get("selected_cell")
    for rectangle, info in app._spatial_rectangles:
        key = (int(info["polygon_local_row"]), int(info["polygon_local_col"]))
        if selected == key:
            rectangle.set_linewidth(2.4)
            rectangle.set_edgecolor("#d62728")
        else:
            rectangle.set_linewidth(0.7)
            rectangle.set_edgecolor("#666666")
    if app._spatial_rectangles:
        app.spatial_canvas.draw_idle()


def clear_spatial_selection(app: Any) -> None:
    """面ビュー上の選択セルを解除する。"""
    if app._spatial_payload is None:
        return
    app._spatial_payload["selected_cell"] = None
    highlight_spatial_selected_cell(app)
    app._update_test_summary()


def on_spatial_canvas_click(app: Any, event: Any) -> None:
    """面ビュークリックでセル選択を反映する。"""
    if event.xdata is None or event.ydata is None or app._spatial_payload is None:
        return
    picked = None
    for _, info in app._spatial_rectangles:
        if (
            float(info["minx"]) <= float(event.xdata) <= float(info["maxx"])
            and float(info["miny"]) <= float(event.ydata) <= float(info["maxy"])
        ):
            picked = info
            break
    if picked is None:
        return
    apply_spatial_selected_cell(
        app,
        int(picked["polygon_local_row"]),
        int(picked["polygon_local_col"]),
    )


def apply_spatial_selected_cell(app: Any, local_row: int, local_col: int) -> None:
    """面ビューの選択セルを入力欄へ反映する。"""
    app.state.local_row_var.set(str(local_row))
    app.state.local_col_var.set(str(local_col))
    if app._spatial_payload is not None:
        app._spatial_payload["selected_cell"] = (local_row, local_col)
    for item_id, row in app._candidate_items.items():
        if int(row.get("polygon_local_row", -1)) == local_row and int(row.get("polygon_local_col", -1)) == local_col:
            app.candidate_tree.selection_set(item_id)
            app.candidate_tree.focus(item_id)
            break
    highlight_spatial_selected_cell(app)
    app._update_test_summary()


def on_candidate_selected(app: Any, _event: tk.Event[tk.Widget] | None = None) -> None:
    """候補セル選択を流域内行列へ反映する。"""
    selected = app.candidate_tree.selection()
    if not selected:
        return
    row = app._candidate_items.get(selected[0])
    if not row:
        return
    app.state.local_row_var.set(str(int(row["polygon_local_row"])))
    app.state.local_col_var.set(str(int(row["polygon_local_col"])))
    app.state.polygon_name_var.set(str(row["polygon_name"]))
    if app._spatial_payload is not None:
        app._spatial_payload["selected_cell"] = (
            int(row["polygon_local_row"]),
            int(row["polygon_local_col"]),
        )
        highlight_spatial_selected_cell(app)
    app._update_test_summary()


def handle_render_spatial_view(app: Any) -> None:
    """面的可視化ビューを描画する。"""
    try:
        db_path = validate_db_path(app)
        polygon_name = validate_polygon_name(app)
        if not app._validate_spatial_timestamp_inline():
            raise ValueError("面ビュー時刻の入力を修正してください。")
        observed_at = _parse_datetime(app.state.spatial_timestamp_var.get().strip())
        metric = app.state.get_spatial_metric()
        preferred_dataset_id = app._get_preferred_dataset_id()

        def worker() -> dict[str, Any]:
            return build_spatial_view_payload(
                db_path=db_path,
                polygon_name=polygon_name,
                observed_at=observed_at,
                metric=metric,
                dataset_id=preferred_dataset_id,
            )

        def on_success(payload: dict[str, Any]) -> None:
            render_spatial_payload(app, payload)
            app._record_last_run(
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

        app._start_background_task(
            action_name="render-spatial-view",
            busy_text="面ビューを描画しています...",
            user_error_message="面ビュー描画に失敗しました。",
            worker=worker,
            on_success=on_success,
        )
    except Exception as exc:
        app._record_last_run(action="render-spatial-view", success=False, error=str(exc))
        app._show_error("面ビュー描画に失敗しました。", detail=str(exc))


def handle_init_db(app: Any) -> None:
    """DB 初期化を実行する。"""
    try:
        db_path = validate_db_path(app)
        app._validate_db_path_inline()

        def worker() -> str:
            with open_db(db_path) as conn:
                initialize_schema(conn)
            return db_path

        def on_success(result: str) -> None:
            app._invalidate_db_related_caches(result)
            app._persist_settings()
            app._load_db_metadata()
            app._record_last_run(action="init-db", success=True, outputs=[result])
            LOGGER.info("DB を初期化しました: %s", result)

        app._start_background_task(
            action_name="init-db",
            busy_text="DB を初期化しています...",
            user_error_message="DB 初期化に失敗しました。",
            worker=worker,
            on_success=on_success,
        )
    except Exception as exc:
        app._show_error("DB 初期化に失敗しました。", detail=str(exc))


def handle_ingest(app: Any) -> None:
    """取り込みを実行する。"""
    try:
        db_path = validate_db_path(app)
        input_paths = validate_input_paths(app)
        polygon_dir = app.state.polygon_dir_var.get().strip() or None
        ingest_dataset_id = app.state.ingest_dataset_id_var.get().strip() or None
        app._validate_input_paths_inline()
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
                    input_paths=cast(list[str | Path], input_paths),
                    polygon_dir=polygon_dir,
                )
            return input_paths

        def on_success(result: list[str]) -> None:
            app._invalidate_db_related_caches(db_path)
            app._persist_settings()
            app._load_db_metadata()
            app._record_last_run(action="ingest", success=True, outputs=result)
            LOGGER.info("取り込みが完了しました。件数=%s", len(result))

        app._start_background_task(
            action_name="ingest",
            busy_text="取り込みを実行しています...",
            user_error_message="取り込みに失敗しました。",
            worker=worker,
            on_success=on_success,
        )
    except Exception as exc:
        app._show_error("取り込みに失敗しました。", detail=str(exc))


def handle_list_candidates(app: Any) -> None:
    """候補セル一覧を更新する。"""
    try:
        db_path = validate_db_path(app)
        polygon_name = validate_polygon_name(app)
        preferred_dataset = app._get_preferred_dataset_id()
        cache_key = (db_path, polygon_name, preferred_dataset)

        def worker() -> Any:
            cached = app._candidate_frame_cache.get(cache_key)
            if cached is not None:
                return cached.copy()
            frame = list_candidate_cells(db_path=db_path, dataset_id=preferred_dataset, polygon_name=polygon_name)
            app._candidate_frame_cache[cache_key] = frame.copy()
            return frame

        def on_success(frame: Any) -> None:
            populate_candidate_tree(app, frame)
            app._persist_settings()
            app._record_last_run(action="list-cells", success=True, outputs=[f"候補セル数={len(frame)}"])
            LOGGER.info("候補セル一覧を更新しました。件数=%s", len(frame))
            if frame.empty:
                app._show_info("候補セルは見つかりませんでした。")

        app._start_background_task(
            action_name="list-cells",
            busy_text="候補セル一覧を更新しています...",
            user_error_message="候補セル一覧更新に失敗しました。",
            worker=worker,
            on_success=on_success,
        )
    except Exception as exc:
        app._show_error("候補セル一覧更新に失敗しました。", detail=str(exc))


def handle_plot(app: Any) -> None:
    """イベントグラフを出力する。"""
    try:
        db_path = validate_db_path(app)
        polygon_name = validate_polygon_name(app)
        view_start, view_end = validate_plot_times(app)
        out_dir = app.state.out_dir_var.get().strip()
        if not out_dir:
            raise ValueError("出力先フォルダを指定してください。")
        series_mode = app.state.get_series_mode()
        local_row = None
        local_col = None
        if series_mode == "cell":
            if not app.state.local_row_var.get().strip() or not app.state.local_col_var.get().strip():
                raise ValueError("セルモードでは流域内行と流域内列を指定してください。")
            local_row = int(app.state.local_row_var.get().strip())
            local_col = int(app.state.local_col_var.get().strip())
        preferred_dataset_id = app._get_preferred_dataset_id()

        def worker() -> Any:
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

        def on_success(paths: Any) -> None:
            path_strings = [str(path) for path in paths]
            app._persist_settings()
            app._record_last_run(action="plot", success=True, outputs=path_strings)
            LOGGER.info("グラフ出力が完了しました。件数=%s", len(paths))

        app._start_background_task(
            action_name="plot",
            busy_text="グラフを出力しています...",
            user_error_message="グラフ出力に失敗しました。",
            worker=worker,
            on_success=on_success,
        )
    except Exception as exc:
        app._show_error("グラフ出力に失敗しました。", detail=str(exc))


def handle_save_test_context(app: Any) -> None:
    """現在状態を JSON として保存する。"""
    try:
        path = app._save_context()
        LOGGER.info("テスト状態を保存しました: %s", path)
    except Exception as exc:
        app._show_error("テスト状態の保存に失敗しました。", detail=str(exc))


def handle_save_widget_tree(app: Any) -> None:
    """widget tree を保存する。"""
    try:
        path = app._save_widget_tree()
        LOGGER.info("ウィジェット状態を保存しました: %s", path)
    except Exception as exc:
        app._show_error("ウィジェット状態の保存に失敗しました。", detail=str(exc))


def handle_save_screenshot(app: Any) -> None:
    """画面を保存する。"""
    try:
        path = app._save_screenshot()
        if path is None:
            raise RuntimeError("画面保存に失敗しました。")
        LOGGER.info("画面を保存しました: %s", path)
    except Exception as exc:
        app._show_error("画面保存に失敗しました。", detail=str(exc))


def handle_save_log(app: Any) -> None:
    """ログをテキストへ保存する。"""
    try:
        path = app._save_log()
        LOGGER.info("ログを保存しました: %s", path)
    except Exception as exc:
        app._show_error("ログ保存に失敗しました。", detail=str(exc))
