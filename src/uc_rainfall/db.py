from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

from .models import DatasetRecord, GridDefinition, PolygonRecord
from .schema import SCHEMA_SQL


def connect(db_path: str | Path) -> sqlite3.Connection:
    """SQLite データベースへ接続し、基本設定を適用する。"""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def open_db(db_path: str | Path):
    """SQLite 接続のオープン/クローズを管理するコンテキスト。"""
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def initialize_schema(conn: sqlite3.Connection) -> None:
    """必要なテーブルとインデックスを作成する。"""
    conn.executescript(SCHEMA_SQL)


def upsert_dataset(conn: sqlite3.Connection, record: DatasetRecord) -> None:
    """データセットメタ情報を登録または更新する。"""
    conn.execute(
        """
        INSERT INTO datasets(dataset_id, source_type, source_dir, time_start, time_end, crs_raw, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(dataset_id) DO UPDATE SET
          source_type=excluded.source_type,
          source_dir=excluded.source_dir,
          time_start=excluded.time_start,
          time_end=excluded.time_end,
          crs_raw=excluded.crs_raw
        """,
        (
            record.dataset_id,
            record.source_type,
            record.source_dir,
            record.time_start.isoformat() if record.time_start else None,
            record.time_end.isoformat() if record.time_end else None,
            record.crs_raw,
            record.created_at.isoformat(),
        ),
    )


def upsert_grid(conn: sqlite3.Connection, grid: GridDefinition) -> None:
    """格子定義を登録または更新する。"""
    conn.execute(
        """
        INSERT INTO grids(dataset_id, grid_crs, origin_x, origin_y, cell_width, cell_height, rows, cols)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(dataset_id) DO UPDATE SET
          grid_crs=excluded.grid_crs,
          origin_x=excluded.origin_x,
          origin_y=excluded.origin_y,
          cell_width=excluded.cell_width,
          cell_height=excluded.cell_height,
          rows=excluded.rows,
          cols=excluded.cols
        """,
        (
            grid.dataset_id,
            grid.grid_crs,
            grid.origin_x,
            grid.origin_y,
            grid.cell_width,
            grid.cell_height,
            grid.rows,
            grid.cols,
        ),
    )


def replace_cell_timeseries(
    conn: sqlite3.Connection,
    dataset_id: str,
    rows: Iterable[tuple[str, int, int, float, float, float | None, str | None]],
) -> None:
    """指定 `dataset_id` のセル時系列を全置換する。"""
    conn.execute("DELETE FROM cell_timeseries WHERE dataset_id = ?", (dataset_id,))
    conn.executemany(
        """
        INSERT INTO cell_timeseries(dataset_id, observed_at, row, col, x_center, y_center, rainfall_mm, quality)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ((dataset_id, *row) for row in rows),
    )


def upsert_polygons(conn: sqlite3.Connection, polygons: Iterable[PolygonRecord]) -> None:
    """流域ポリゴンのメタ情報を登録または更新する。"""
    conn.executemany(
        """
        INSERT INTO polygons(polygon_id, polygon_name, polygon_group, polygon_crs, minx, miny, maxx, maxy, file_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(polygon_id) DO UPDATE SET
          polygon_name=excluded.polygon_name,
          polygon_group=excluded.polygon_group,
          polygon_crs=excluded.polygon_crs,
          minx=excluded.minx,
          miny=excluded.miny,
          maxx=excluded.maxx,
          maxy=excluded.maxy,
          file_path=excluded.file_path
        """,
        (
            (
                polygon.polygon_id,
                polygon.polygon_name,
                polygon.polygon_group,
                polygon.polygon_crs,
                polygon.minx,
                polygon.miny,
                polygon.maxx,
                polygon.maxy,
                polygon.file_path,
            )
            for polygon in polygons
        ),
    )


def replace_polygon_cell_map(
    conn: sqlite3.Connection,
    dataset_id: str,
    rows: Iterable[tuple[str, int, int, int, str]],
) -> None:
    """指定 `dataset_id` の流域-セル対応表を全置換する。"""
    conn.execute("DELETE FROM polygon_cell_map WHERE dataset_id = ?", (dataset_id,))
    conn.executemany(
        """
        INSERT INTO polygon_cell_map(dataset_id, polygon_id, row, col, inside_flag, selection_method)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ((dataset_id, *row) for row in rows),
    )
