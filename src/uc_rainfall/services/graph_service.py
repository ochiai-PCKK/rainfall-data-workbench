from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pandas as pd

from ..db import open_db
from ..graph import add_metric_columns, find_metric_events, render_metric_chart
from .candidate_service import _build_canonical_candidate_cells

LOGGER = logging.getLogger(__name__)


def _safe_token(value: str) -> str:
    """ファイル名に使いづらい文字を安全な文字へ置き換える。"""
    return re.sub(r"[^\w\-]+", "_", value).strip("_")


def _grid_matches(left: pd.Series, right: pd.Series, *, tol: float = 1e-6) -> bool:
    """格子定義が同一かどうかを許容誤差付きで判定する。"""
    left_grid_crs = str(left["grid_crs"])
    right_grid_crs = str(right["grid_crs"])
    left_origin_x = float(cast(Any, left["origin_x"]))
    right_origin_x = float(cast(Any, right["origin_x"]))
    left_origin_y = float(cast(Any, left["origin_y"]))
    right_origin_y = float(cast(Any, right["origin_y"]))
    left_cell_width = float(cast(Any, left["cell_width"]))
    right_cell_width = float(cast(Any, right["cell_width"]))
    left_cell_height = float(cast(Any, left["cell_height"]))
    right_cell_height = float(cast(Any, right["cell_height"]))
    left_rows = int(cast(Any, left["rows"]))
    right_rows = int(cast(Any, right["rows"]))
    left_cols = int(cast(Any, left["cols"]))
    right_cols = int(cast(Any, right["cols"]))
    return (
        left_grid_crs == right_grid_crs
        and abs(left_origin_x - right_origin_x) <= tol
        and abs(left_origin_y - right_origin_y) <= tol
        and abs(left_cell_width - right_cell_width) <= tol
        and abs(left_cell_height - right_cell_height) <= tol
        and left_rows == right_rows
        and left_cols == right_cols
    )


def _sort_dataset_ids(dataset_ids: list[str], *, anchor_dataset_id: str | None) -> list[str]:
    """優先データセットを先頭にして dataset_id 一覧を整列する。"""
    unique_ids = list(dict.fromkeys(dataset_ids))
    if anchor_dataset_id is None or anchor_dataset_id not in unique_ids:
        return sorted(unique_ids)
    return [anchor_dataset_id] + sorted(dataset_id for dataset_id in unique_ids if dataset_id != anchor_dataset_id)


def _fetch_compatible_frames(
    *,
    conn,
    dataset_id: str,
    polygon_name: str,
    row: int,
    col: int,
    calc_start: datetime,
    view_end: datetime,
) -> tuple[pd.DataFrame, list[str]]:
    """同一格子定義を持つデータセット群から、指定セルの時系列を取得する。"""
    membership = conn.execute(
        """
        SELECT 1
        FROM polygon_cell_map pcm
        JOIN polygons p ON p.polygon_id = pcm.polygon_id
        WHERE pcm.dataset_id = ? AND p.polygon_name = ? AND pcm.row = ? AND pcm.col = ?
        """,
        (dataset_id, polygon_name, row, col),
    ).fetchone()
    if membership is None:
        raise ValueError(f"row={row}, col={col} は流域 {polygon_name} の候補セルではありません")

    grids = pd.read_sql_query(
        """
        SELECT dataset_id, grid_crs, origin_x, origin_y, cell_width, cell_height, rows, cols
        FROM grids
        """,
        conn,
    )
    compatible_dataset_ids = _load_compatible_dataset_ids(grids, anchor_dataset_id=dataset_id)

    placeholders = ",".join("?" for _ in compatible_dataset_ids)
    frame = pd.read_sql_query(
        f"""
        SELECT dataset_id, observed_at, rainfall_mm
        FROM cell_timeseries
        WHERE dataset_id IN ({placeholders}) AND row = ? AND col = ? AND observed_at BETWEEN ? AND ?
        ORDER BY observed_at
        """,
        conn,
        params=[
            *compatible_dataset_ids,
            row,
            col,
            calc_start.isoformat(timespec="seconds"),
            view_end.isoformat(timespec="seconds"),
        ],
    )
    return frame, compatible_dataset_ids


def _load_dataset_grids(conn) -> pd.DataFrame:
    """登録済み格子定義を取得する。"""
    return pd.read_sql_query(
        """
        SELECT dataset_id, grid_crs, origin_x, origin_y, cell_width, cell_height, rows, cols
        FROM grids
        """,
        conn,
    )


def _load_compatible_dataset_ids_for_dataset(
    conn,
    *,
    dataset_id: str,
) -> list[str]:
    """指定 dataset と同じ格子定義を持つ dataset 一覧を返す。"""
    grids = _load_dataset_grids(conn)
    anchor = grids.loc[grids["dataset_id"] == dataset_id]
    if anchor.empty:
        raise ValueError(f"格子定義が見つかりません: dataset_id={dataset_id}")
    anchor_row = anchor.iloc[0]
    compatible = [
        str(row["dataset_id"])
        for _, row in grids.iterrows()
        if _grid_matches(row, anchor_row)
    ]
    return _sort_dataset_ids(compatible, anchor_dataset_id=dataset_id)


def _load_compatible_dataset_ids(
    grids: pd.DataFrame,
    *,
    anchor_dataset_id: str,
) -> list[str]:
    """格子定義 DataFrame から、起点と同一格子の dataset 一覧を返す。"""
    anchor = grids.loc[grids["dataset_id"] == anchor_dataset_id]
    if anchor.empty:
        raise ValueError(f"格子定義が見つかりません: dataset_id={anchor_dataset_id}")
    anchor_row = anchor.iloc[0]
    compatible = [
        str(row["dataset_id"])
        for _, row in grids.iterrows()
        if _grid_matches(row, anchor_row)
    ]
    return _sort_dataset_ids(compatible, anchor_dataset_id=anchor_dataset_id)


def _load_candidate_cell_table(
    conn,
    *,
    polygon_name: str,
    dataset_ids: list[str] | None = None,
) -> pd.DataFrame:
    """候補セル一覧を座標付きで取得する。"""
    sql = """
    SELECT
      pcm.dataset_id,
      p.polygon_name,
      pcm.row,
      pcm.col,
      pcm.polygon_local_row,
      pcm.polygon_local_col,
      c.x_center,
      c.y_center,
      pcm.inside_flag
    FROM polygon_cell_map pcm
    JOIN polygons p ON p.polygon_id = pcm.polygon_id
    JOIN (
      SELECT dataset_id, row, col, MIN(x_center) AS x_center, MIN(y_center) AS y_center
      FROM cell_timeseries
      GROUP BY dataset_id, row, col
    ) c
      ON c.dataset_id = pcm.dataset_id
     AND c.row = pcm.row
     AND c.col = pcm.col
    WHERE p.polygon_name = ?
    """
    params: list[object] = [polygon_name]
    if dataset_ids:
        placeholders = ",".join("?" for _ in dataset_ids)
        sql += f" AND pcm.dataset_id IN ({placeholders})"
        params.extend(dataset_ids)
    sql += " ORDER BY pcm.dataset_id, pcm.row, pcm.col"
    return pd.read_sql_query(sql, conn, params=params)


def _resolve_anchor_cell(
    conn,
    *,
    dataset_id: str | None,
    polygon_name: str,
    row: int | None,
    col: int | None,
    local_row: int | None,
    local_col: int | None,
) -> tuple[int, int, int, int, float, float]:
    """起点セルを source row/col または流域内 row/col から解決する。"""
    dataset_ids = [dataset_id] if dataset_id is not None else None
    frame = _load_candidate_cell_table(conn, polygon_name=polygon_name, dataset_ids=dataset_ids)
    if frame.empty:
        raise ValueError(f"流域 {polygon_name} の候補セルが見つかりません")

    filtered = frame
    if row is not None and col is not None:
        filtered = filtered[(filtered["row"] == row) & (filtered["col"] == col)]
    elif local_row is not None and local_col is not None:
        canonical = _build_canonical_candidate_cells(frame)
        matched = canonical[
            (canonical["polygon_local_row"] == local_row)
            & (canonical["polygon_local_col"] == local_col)
        ]
        if matched.empty:
            raise ValueError(f"流域内行列 ({local_row}, {local_col}) に一致する候補セルが見つかりません")
        target = matched.iloc[0]
        filtered = frame[
            (frame["x_center"].sub(float(target["x_center"])).abs() <= 1e-6)
            & (frame["y_center"].sub(float(target["y_center"])).abs() <= 1e-6)
        ]
    else:
        raise ValueError("cell モードでは --row/--col または --local-row/--local-col の指定が必要です")

    if filtered.empty:
        raise ValueError(f"指定セルが流域 {polygon_name} の候補セルに見つかりません")
    if len(filtered) > 1 and dataset_id is None:
        filtered_df = cast(pd.DataFrame, filtered)
        filtered = cast(pd.DataFrame, filtered_df.sort_values(by=["dataset_id", "row", "col"]).head(1))
    elif len(filtered) > 1:
        raise ValueError("指定セルが一意に定まりません")

    item = filtered.iloc[0]
    canonical = _build_canonical_candidate_cells(frame)
    canonical_match = canonical[
        (canonical["x_center"].sub(float(item["x_center"])).abs() <= 1e-6)
        & (canonical["y_center"].sub(float(item["y_center"])).abs() <= 1e-6)
    ]
    if canonical_match.empty:
        raise ValueError("流域内ローカル行列番号を解決できません")
    local_item = canonical_match.iloc[0]
    return (
        int(item["row"]),
        int(item["col"]),
        int(local_item["polygon_local_row"]),
        int(local_item["polygon_local_col"]),
        float(item["x_center"]),
        float(item["y_center"]),
    )


def _find_position_matched_cells(
    conn,
    *,
    polygon_name: str,
    anchor_x: float,
    anchor_y: float,
    dataset_ids: list[str] | None = None,
    tol: float = 1e-6,
) -> pd.DataFrame:
    """流域内候補セルの中から、起点セルと同じ中心座標を持つセルを探す。"""
    frame = _load_candidate_cell_table(conn, polygon_name=polygon_name, dataset_ids=dataset_ids)
    if frame.empty:
        raise ValueError(f"流域 {polygon_name} の候補セルが見つかりません")

    matched = frame[
        (frame["x_center"].sub(anchor_x).abs() <= tol)
        & (frame["y_center"].sub(anchor_y).abs() <= tol)
    ].copy()
    if matched.empty:
        raise ValueError("同一位置に一致する候補セルが見つかりません")

    counts = cast(pd.Series, matched.groupby("dataset_id").size())
    duplicates = cast(pd.Series, counts[counts > 1])
    if not duplicates.empty:
        raise ValueError(f"同一 dataset 内で位置一致セルが複数見つかりました: {duplicates.to_dict()}")
    return cast(pd.DataFrame, matched)


def _fetch_position_matched_frames(
    conn,
    *,
    matched_cells: pd.DataFrame,
    calc_start: datetime,
    view_end: datetime,
) -> tuple[pd.DataFrame, list[str]]:
    """位置一致したセル群の時系列を取得する。"""
    frames: list[pd.DataFrame] = []
    dataset_ids: list[str] = []
    for _, item in matched_cells.iterrows():
        dataset_id = str(item["dataset_id"])
        row = int(cast(Any, item["row"]))
        col = int(cast(Any, item["col"]))
        dataset_ids.append(dataset_id)
        part = pd.read_sql_query(
            """
            SELECT dataset_id, observed_at, rainfall_mm
            FROM cell_timeseries
            WHERE dataset_id = ? AND row = ? AND col = ? AND observed_at BETWEEN ? AND ?
            ORDER BY observed_at
            """,
            conn,
            params=[
                dataset_id,
                row,
                col,
                calc_start.isoformat(timespec="seconds"),
                view_end.isoformat(timespec="seconds"),
            ],
        )
        frames.append(part)

    if not frames:
        return pd.DataFrame(), []
    return pd.concat(frames, ignore_index=True), dataset_ids


def _deduplicate_rows(
    frame: pd.DataFrame,
    *,
    anchor_dataset_id: str,
    subset_cols: list[str],
) -> pd.DataFrame:
    """同一キーの重複行を起点データセット優先で1件に絞る。"""
    if frame.empty:
        return frame

    dataset_priority = {anchor_dataset_id: 0}
    next_priority = 1
    for dataset_id in frame["dataset_id"].drop_duplicates().tolist():
        if dataset_id not in dataset_priority:
            dataset_priority[dataset_id] = next_priority
            next_priority += 1

    ranked = frame.copy()
    ranked["priority"] = ranked["dataset_id"].map(lambda dataset_id: dataset_priority.get(str(dataset_id), 9999))
    ranked = cast(pd.DataFrame, ranked.sort_values(by=[*subset_cols, "priority", "dataset_id"]).reset_index(drop=True))

    duplicated = ranked[ranked.duplicated(subset=subset_cols, keep=False)]
    if not duplicated.empty:
        grouped = duplicated.groupby(subset_cols)["dataset_id"].apply(list)
        LOGGER.info("重複グループ数=%s 優先データセット=%s", len(grouped), anchor_dataset_id)
        max_examples = 5
        for idx, (key, dataset_ids) in enumerate(grouped.items()):
            if idx >= max_examples:
                LOGGER.info("重複ログを省略しました。残り=%s", len(grouped) - max_examples)
                break
            LOGGER.info(
                "重複キー=%s データセット=%s 採用=%s",
                key,
                dataset_ids,
                dataset_ids[0],
            )

    deduped = cast(pd.DataFrame, ranked.drop_duplicates(subset=subset_cols, keep="first").drop(columns=["priority"]))
    return deduped


def _build_continuous_hourly_frame(
    frame: pd.DataFrame,
    *,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    group_cols: list[str] | None = None,
) -> pd.DataFrame:
    """欠測時刻を補って連続した1時間時系列へ整形する。"""
    if frame.empty:
        return frame

    if group_cols:
        result_frames: list[pd.DataFrame] = []
        for keys, group in frame.groupby(group_cols, sort=False):
            indexed = group.set_index("observed_at").sort_index()
            index = cast(pd.DatetimeIndex, indexed.index)
            range_start = (
                pd.Timestamp(start_at).floor("h")
                if start_at is not None
                else pd.Timestamp(cast(Any, index.min())).floor("h")
            )
            local_end = (
                pd.Timestamp(end_at).floor("h")
                if end_at is not None
                else pd.Timestamp(cast(Any, index.max())).floor("h")
            )
            full_index = pd.date_range(range_start, local_end, freq="h")
            aligned = indexed.reindex(full_index)
            aligned.index.name = "observed_at"
            aligned["rainfall_mm"] = pd.to_numeric(aligned["rainfall_mm"], errors="coerce")
            rainfall_series = cast(pd.Series, aligned["rainfall_mm"])
            if "quality" in aligned.columns:
                quality_series = cast(pd.Series, aligned["quality"])
                aligned["quality"] = quality_series
                aligned.loc[quality_series.isna() & rainfall_series.isna(), "quality"] = "missing"
                aligned.loc[quality_series.isna() & rainfall_series.notna(), "quality"] = "normal"
            else:
                aligned["quality"] = "normal"
                aligned.loc[rainfall_series.isna(), "quality"] = "missing"
            if "overlap_ratio" in indexed.columns:
                ratio_series = cast(pd.Series, pd.to_numeric(indexed["overlap_ratio"], errors="coerce")).dropna()
                aligned["overlap_ratio"] = ratio_series.iloc[0] if not ratio_series.empty else float("nan")
            if not isinstance(keys, tuple):
                keys = (keys,)
            for column, value in zip(group_cols, keys):
                aligned[column] = value
            result_frames.append(aligned.reset_index())
        return pd.concat(result_frames, ignore_index=True)

    indexed = frame.set_index("observed_at").sort_index()
    index = cast(pd.DatetimeIndex, indexed.index)
    range_start = (
        pd.Timestamp(start_at).floor("h")
        if start_at is not None
        else pd.Timestamp(cast(Any, index.min())).floor("h")
    )
    range_end = (
        pd.Timestamp(end_at).floor("h")
        if end_at is not None
        else pd.Timestamp(cast(Any, index.max())).floor("h")
    )
    full_index = pd.date_range(range_start, range_end, freq="h")
    aligned = indexed.reindex(full_index)
    aligned.index.name = "observed_at"
    aligned["rainfall_mm"] = pd.to_numeric(aligned["rainfall_mm"], errors="coerce")
    rainfall_series = cast(pd.Series, aligned["rainfall_mm"])
    if "quality" in aligned.columns:
        quality_series = cast(pd.Series, aligned["quality"])
        aligned["quality"] = quality_series
        aligned.loc[quality_series.isna() & rainfall_series.isna(), "quality"] = "missing"
        aligned.loc[quality_series.isna() & rainfall_series.notna(), "quality"] = "normal"
    else:
        aligned["quality"] = "normal"
        aligned.loc[rainfall_series.isna(), "quality"] = "missing"
    return aligned.reset_index()


def _load_candidate_cells(conn, *, dataset_id: str | None, polygon_name: str) -> pd.DataFrame:
    """指定流域に属する候補セル一覧を DB から取得する。"""
    sql = """
    SELECT pcm.dataset_id, pcm.row, pcm.col
    FROM polygon_cell_map pcm
    JOIN polygons p ON p.polygon_id = pcm.polygon_id
    WHERE p.polygon_name = ?
    """
    params: list[object] = [polygon_name]
    if dataset_id is not None:
        sql += " AND pcm.dataset_id = ?"
        params.append(dataset_id)
    sql += " ORDER BY pcm.dataset_id, pcm.row, pcm.col"
    frame = pd.read_sql_query(sql, conn, params=params)
    if frame.empty:
        raise ValueError(f"流域 {polygon_name} の候補セルが見つかりません")
    return frame


def _fetch_polygon_frames(
    *,
    conn,
    dataset_ids: list[str],
    anchor_dataset_id: str | None,
    polygon_name: str,
    calc_start: datetime,
    view_end: datetime,
) -> pd.DataFrame:
    """指定流域に属する全候補セルの時系列を取得する。"""
    placeholders = ",".join("?" for _ in dataset_ids)
    return pd.read_sql_query(
        f"""
        SELECT c.dataset_id, c.observed_at, c.row, c.col, c.rainfall_mm, pcm.overlap_ratio
        FROM cell_timeseries c
        JOIN polygon_cell_map pcm
          ON pcm.dataset_id = c.dataset_id AND pcm.row = c.row AND pcm.col = c.col
        JOIN polygons p
          ON p.polygon_id = pcm.polygon_id
        WHERE c.dataset_id IN ({placeholders})
          AND p.polygon_name = ?
          AND c.observed_at BETWEEN ? AND ?
        ORDER BY c.observed_at, c.row, c.col
        """,
        conn,
        params=[
            *dataset_ids,
            polygon_name,
            calc_start.isoformat(timespec="seconds"),
            view_end.isoformat(timespec="seconds"),
        ],
    )


def _aggregate_polygon_frame(frame: pd.DataFrame, *, mode: str) -> pd.DataFrame:
    """流域内セル時系列を合計または平均へ集約する。"""
    grouped = frame.groupby("observed_at", sort=True)
    if mode == "polygon_sum":
        rainfall = grouped["rainfall_mm"].agg(lambda s: s.sum(min_count=1))
    elif mode == "polygon_mean":
        rainfall = grouped["rainfall_mm"].mean()
    elif mode == "polygon_weighted_sum":
        rainfall = grouped.apply(
            lambda g: (
                cast(pd.Series, pd.to_numeric(g["rainfall_mm"], errors="coerce"))
                * cast(pd.Series, pd.to_numeric(g["overlap_ratio"], errors="coerce"))
            ).sum(min_count=1)
        )
    elif mode == "polygon_weighted_mean":
        def _weighted_mean(group: pd.DataFrame):
            values = cast(pd.Series, pd.to_numeric(group["rainfall_mm"], errors="coerce"))
            weights = cast(pd.Series, pd.to_numeric(group["overlap_ratio"], errors="coerce"))
            valid = values.notna() & weights.notna()
            if not bool(valid.any()):
                return float("nan")
            return float((values[valid] * weights[valid]).sum() / weights[valid].sum())

        rainfall = grouped.apply(_weighted_mean)
    else:
        raise ValueError(f"未対応の集計モードです: {mode}")

    quality = grouped["rainfall_mm"].agg(
        lambda s: "missing" if cast(pd.Series, s).notna().sum() == 0 else "normal"
    )
    result = pd.DataFrame(
        {
            "observed_at": cast(pd.Series, rainfall).index,
            "rainfall_mm": cast(pd.Series, rainfall).to_numpy(),
            "quality": cast(pd.Series, quality).to_numpy(),
        }
    )
    return result.reset_index(drop=True)


def generate_metric_event_charts(
    *,
    db_path: str | Path,
    dataset_id: str | None,
    polygon_name: str,
    row: int | None,
    col: int | None,
    local_row: int | None,
    local_col: int | None,
    series_mode: str,
    view_start: datetime,
    view_end: datetime,
    out_dir: str | Path,
) -> list[Path]:
    """指定セルまたは流域集計系列から最大イベントグラフ群を出力する。"""
    calc_start = view_start - timedelta(hours=48)
    with open_db(db_path) as conn:
        if series_mode == "cell":
            (
                resolved_row,
                resolved_col,
                resolved_local_row,
                resolved_local_col,
                anchor_x,
                anchor_y,
            ) = _resolve_anchor_cell(
                conn=conn,
                dataset_id=dataset_id,
                polygon_name=polygon_name,
                row=row,
                col=col,
                local_row=local_row,
                local_col=local_col,
            )
            if dataset_id is not None:
                dataset_ids = _load_compatible_dataset_ids_for_dataset(conn, dataset_id=dataset_id)
            else:
                dataset_ids = None
            matched_cells = _find_position_matched_cells(
                conn,
                polygon_name=polygon_name,
                anchor_x=anchor_x,
                anchor_y=anchor_y,
                dataset_ids=dataset_ids,
            )
            frame, compatible_dataset_ids = _fetch_position_matched_frames(
                conn,
                matched_cells=matched_cells,
                calc_start=calc_start,
                view_end=view_end,
            )
            row = resolved_row
            col = resolved_col
            local_row = resolved_local_row
            local_col = resolved_local_col
            compatible_dataset_ids = _sort_dataset_ids(compatible_dataset_ids, anchor_dataset_id=dataset_id)
            LOGGER.info(
                "位置一致セルを使用します: x_center=%s y_center=%s 一致データセット=%s",
                anchor_x,
                anchor_y,
                compatible_dataset_ids,
            )
        else:
            candidate_cells = _load_candidate_cells(
                conn,
                dataset_id=dataset_id if dataset_id is not None else None,
                polygon_name=polygon_name,
            )
            compatible_dataset_ids = [dataset_id] if dataset_id is not None else sorted(
                candidate_cells["dataset_id"].drop_duplicates().tolist()
            )
            LOGGER.info(
                "流域集計を実行します: polygon=%s 候補セル数=%s mode=%s",
                polygon_name,
                len(candidate_cells),
                series_mode,
            )
            frame = _fetch_polygon_frames(
                conn=conn,
                dataset_ids=compatible_dataset_ids,
                anchor_dataset_id=dataset_id,
                polygon_name=polygon_name,
                calc_start=calc_start,
                view_end=view_end,
            )

    if frame.empty:
        raise ValueError("指定条件に該当する時系列データが見つかりません")

    LOGGER.info("使用データセット=%s", compatible_dataset_ids)
    frame["observed_at"] = pd.to_datetime(frame["observed_at"], errors="coerce")
    frame["rainfall_mm"] = pd.to_numeric(frame["rainfall_mm"], errors="coerce")
    frame = frame.dropna(subset=["observed_at"]).sort_values("observed_at").reset_index(drop=True)
    if series_mode == "cell":
        anchor_for_dedup = dataset_id or compatible_dataset_ids[0]
        frame = _deduplicate_rows(frame, anchor_dataset_id=anchor_for_dedup, subset_cols=["observed_at"])
        frame = _build_continuous_hourly_frame(frame, start_at=calc_start, end_at=view_end)
    else:
        anchor_for_dedup = dataset_id or compatible_dataset_ids[0]
        frame = _deduplicate_rows(frame, anchor_dataset_id=anchor_for_dedup, subset_cols=["observed_at", "row", "col"])
        frame = _build_continuous_hourly_frame(
            frame,
            start_at=calc_start,
            end_at=view_end,
            group_cols=["row", "col"],
        )
        frame = _aggregate_polygon_frame(frame, mode=series_mode)
    frame = add_metric_columns(frame)

    output_paths: list[Path] = []
    output_dataset_token = dataset_id or "all"
    for event in find_metric_events(frame, view_start=view_start, view_end=view_end):
        event_stamp = event.occurred_at.strftime("%Y%m%dT%H%M%SJST")
        if series_mode == "cell":
            filename = (
                f"{_safe_token(output_dataset_token)}_{_safe_token(polygon_name)}_"
                f"lr{local_row}_lc{local_col}_{event.metric}_{event_stamp}.png"
            )
            title = f"{polygon_name} セル[{local_row},{local_col}] {event.metric}最大雨量"
        else:
            if series_mode == "polygon_sum":
                suffix = "全セル合計"
            elif series_mode == "polygon_mean":
                suffix = "全セル単純平均"
            elif series_mode == "polygon_weighted_sum":
                suffix = "全セル重み付き合計"
            else:
                suffix = "全セル重み付き平均"
            filename = (
                f"{_safe_token(output_dataset_token)}_{_safe_token(polygon_name)}_"
                f"{_safe_token(suffix)}_{event.metric}_{event_stamp}.png"
            )
            title = f"{polygon_name} {suffix} {event.metric}最大雨量"
        output_paths.append(
            render_metric_chart(
                frame,
                metric=event.metric,
                event_time=event.occurred_at,
                output_path=Path(out_dir) / filename,
                title=title,
            )
        )
    return output_paths
