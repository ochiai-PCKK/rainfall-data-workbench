from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..db import open_db


def _build_canonical_candidate_cells(frame: pd.DataFrame) -> pd.DataFrame:
    """候補セルを中心座標ベースで正規化し、流域内ローカル番号を付与する。"""
    if frame.empty:
        return frame

    work = frame.copy()
    work["x_key"] = work["x_center"].round(6)
    work["y_key"] = work["y_center"].round(6)
    agg_map: dict[str, tuple[str, str]] = {
        "x_center": ("x_center", "mean"),
        "y_center": ("y_center", "mean"),
        "dataset_count": ("dataset_id", "nunique"),
    }
    if "overlap_ratio" in work.columns:
        agg_map["overlap_ratio"] = ("overlap_ratio", "mean")

    unique_cells = work.groupby(["polygon_name", "x_key", "y_key", "inside_flag"], dropna=False).agg(**agg_map).reset_index()

    results: list[pd.DataFrame] = []
    for polygon_name, group in unique_cells.groupby("polygon_name", sort=False):
        group = group.copy()
        y_order = {value: idx for idx, value in enumerate(sorted(group["y_center"].unique(), reverse=True))}
        x_order = {value: idx for idx, value in enumerate(sorted(group["x_center"].unique()))}
        group["polygon_local_row"] = group["y_center"].map(y_order).astype(int)
        group["polygon_local_col"] = group["x_center"].map(x_order).astype(int)
        group = group.drop(columns=["x_key", "y_key"])
        results.append(group)

    merged = pd.concat(results, ignore_index=True)
    return merged.sort_values(["polygon_name", "polygon_local_row", "polygon_local_col"]).reset_index(drop=True)


def list_candidate_cells(
    *,
    db_path: str | Path,
    dataset_id: str | None = None,
    polygon_name: str | None = None,
) -> pd.DataFrame:
    """流域ごとの候補セル一覧を、中心座標ベースで一意化して取得する。"""
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
      pcm.overlap_ratio,
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
    WHERE 1 = 1
    """
    params: list[object] = []
    if dataset_id:
        sql += " AND pcm.dataset_id = ?"
        params.append(dataset_id)
    if polygon_name:
        sql += " AND p.polygon_name = ?"
        params.append(polygon_name)
    sql += " ORDER BY p.polygon_name, pcm.dataset_id, pcm.row, pcm.col"

    with open_db(db_path) as conn:
        frame = pd.read_sql_query(sql, conn, params=params)
    if not frame.empty:
        frame["inside_flag"] = frame["inside_flag"].astype(bool)
    return _build_canonical_candidate_cells(frame)
