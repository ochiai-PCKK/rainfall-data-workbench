from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..db import open_db


def list_candidate_cells(*, db_path: str | Path, dataset_id: str, polygon_name: str | None = None) -> pd.DataFrame:
    """指定データセット・流域に属する候補セル一覧を取得する。"""
    sql = """
    SELECT
      p.polygon_name,
      pcm.row,
      pcm.col,
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
    WHERE pcm.dataset_id = ?
    """
    params: list[object] = [dataset_id]
    if polygon_name:
        sql += " AND p.polygon_name = ?"
        params.append(polygon_name)
    sql += " ORDER BY p.polygon_name, pcm.row, pcm.col"

    with open_db(db_path) as conn:
        frame = pd.read_sql_query(sql, conn, params=params)
    if not frame.empty:
        frame["inside_flag"] = frame["inside_flag"].astype(bool)
    return frame
