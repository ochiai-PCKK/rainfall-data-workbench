from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import logging
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely.geometry import box
from shapely import wkt as shapely_wkt

from ..db import open_db
from ..graph.metrics import METRIC_WINDOWS, add_metric_columns
from .graph_service import _build_continuous_hourly_frame


LOGGER = logging.getLogger(__name__)


def _load_dataset_grid(conn, *, dataset_id: str) -> pd.Series:
    """指定 dataset の格子定義を取得する。"""
    frame = pd.read_sql_query(
        """
        SELECT dataset_id, grid_crs, origin_x, origin_y, cell_width, cell_height, rows, cols
        FROM grids
        WHERE dataset_id = ?
        """,
        conn,
        params=(dataset_id,),
    )
    if frame.empty:
        raise ValueError(f"格子定義が見つかりません: dataset_id={dataset_id}")
    return frame.iloc[0]


def _resolve_spatial_dataset_id(
    conn,
    *,
    polygon_name: str,
    observed_at: datetime,
    dataset_id: str | None,
) -> tuple[str, list[str]]:
    """面ビューに使う dataset_id を解決する。"""
    target_time = observed_at.isoformat(timespec="seconds")
    frame = pd.read_sql_query(
        """
        SELECT DISTINCT d.dataset_id, d.time_start, d.time_end
        FROM datasets d
        JOIN polygon_cell_map pcm ON pcm.dataset_id = d.dataset_id
        JOIN polygons p ON p.polygon_id = pcm.polygon_id
        WHERE p.polygon_name = ?
        ORDER BY d.dataset_id
        """,
        conn,
        params=(polygon_name,),
    )
    if frame.empty:
        raise ValueError(f"流域 {polygon_name} に対応するデータセットが見つかりません")

    def covers(row: pd.Series) -> bool:
        start = row["time_start"]
        end = row["time_end"]
        return (start is None or str(start) <= target_time) and (end is None or str(end) >= target_time)

    candidates = frame[frame.apply(covers, axis=1)]
    if dataset_id is not None:
        matched = candidates[candidates["dataset_id"] == dataset_id]
        if matched.empty:
            raise ValueError(f"指定 dataset_id は {observed_at.isoformat()} をカバーしていません: {dataset_id}")
        return dataset_id, candidates["dataset_id"].tolist()

    if candidates.empty:
        raise ValueError(f"{observed_at.isoformat()} をカバーするデータセットが見つかりません")
    selected = sorted(candidates["dataset_id"].tolist())[0]
    return selected, candidates["dataset_id"].tolist()


def _load_polygon_geometry(conn, *, polygon_name: str) -> tuple[str, Any]:
    """流域ポリゴン geometry と CRS を取得する。"""
    row = conn.execute(
        """
        SELECT polygon_crs, geometry_wkt
        FROM polygons
        WHERE polygon_name = ?
        """,
        (polygon_name,),
    ).fetchone()
    if row is None:
        raise ValueError(f"流域ポリゴンが見つかりません: {polygon_name}")
    return row["polygon_crs"], shapely_wkt.loads(row["geometry_wkt"])


def _load_polygon_cells_for_time(
    conn,
    *,
    dataset_id: str,
    polygon_name: str,
    observed_at: datetime,
) -> pd.DataFrame:
    """指定時刻の流域内セル値一覧を取得する。"""
    target_time = observed_at.isoformat(timespec="seconds")
    return pd.read_sql_query(
        """
        SELECT
          pcm.dataset_id,
          p.polygon_name,
          pcm.row,
          pcm.col,
          pcm.polygon_local_row,
          pcm.polygon_local_col,
          pcm.overlap_ratio,
          ct.x_center,
          ct.y_center,
          ct.rainfall_mm,
          ct.quality
        FROM polygon_cell_map pcm
        JOIN polygons p ON p.polygon_id = pcm.polygon_id
        LEFT JOIN cell_timeseries ct
          ON ct.dataset_id = pcm.dataset_id
         AND ct.row = pcm.row
         AND ct.col = pcm.col
         AND ct.observed_at = ?
        WHERE pcm.dataset_id = ?
          AND p.polygon_name = ?
        ORDER BY pcm.polygon_local_row, pcm.polygon_local_col
        """,
        conn,
        params=(target_time, dataset_id, polygon_name),
    )


def _load_polygon_cell_metric_values(
    conn,
    *,
    dataset_id: str,
    polygon_name: str,
    observed_at: datetime,
    metric: str,
) -> pd.DataFrame:
    """指定時刻のセル単位累加雨量を計算する。"""
    hours = METRIC_WINDOWS[metric]
    calc_start = observed_at - timedelta(hours=hours - 1)
    frame = pd.read_sql_query(
        """
        SELECT
          ct.dataset_id,
          ct.observed_at,
          ct.row,
          ct.col,
          ct.x_center,
          ct.y_center,
          ct.rainfall_mm,
          ct.quality,
          pcm.polygon_local_row,
          pcm.polygon_local_col,
          pcm.overlap_ratio
        FROM cell_timeseries ct
        JOIN polygon_cell_map pcm
          ON pcm.dataset_id = ct.dataset_id AND pcm.row = ct.row AND pcm.col = ct.col
        JOIN polygons p
          ON p.polygon_id = pcm.polygon_id
        WHERE ct.dataset_id = ?
          AND p.polygon_name = ?
          AND ct.observed_at BETWEEN ? AND ?
        ORDER BY ct.row, ct.col, ct.observed_at
        """,
        conn,
        params=(
            dataset_id,
            polygon_name,
            calc_start.isoformat(timespec="seconds"),
            observed_at.isoformat(timespec="seconds"),
        ),
    )
    if frame.empty:
        return frame

    frame["observed_at"] = pd.to_datetime(frame["observed_at"], errors="coerce")
    frame["rainfall_mm"] = pd.to_numeric(frame["rainfall_mm"], errors="coerce")
    continuous = _build_continuous_hourly_frame(
        frame,
        start_at=calc_start,
        end_at=observed_at,
        group_cols=["row", "col"],
    )
    parts: list[pd.DataFrame] = []
    static_columns = [
        "dataset_id",
        "row",
        "col",
        "x_center",
        "y_center",
        "polygon_local_row",
        "polygon_local_col",
        "overlap_ratio",
    ]
    for _, group in continuous.groupby(["row", "col"], sort=False):
        ordered = group.sort_values("observed_at").reset_index(drop=True)
        enriched = add_metric_columns(ordered)
        for column in static_columns:
            if column in ordered.columns:
                enriched[column] = ordered[column].ffill().bfill()
        parts.append(enriched)

    enriched_frame = pd.concat(parts, ignore_index=True)
    target = enriched_frame.loc[
        enriched_frame["observed_at"] == pd.Timestamp(observed_at),
        [
            "dataset_id",
            "row",
            "col",
            "x_center",
            "y_center",
            "polygon_local_row",
            "polygon_local_col",
            "overlap_ratio",
            metric,
        ],
    ].copy()
    if target.empty:
        return target
    target = target.rename(columns={metric: "value"})
    return target


def build_spatial_view_payload(
    *,
    db_path: str | Path,
    polygon_name: str,
    observed_at: datetime,
    metric: str,
    dataset_id: str | None = None,
) -> dict[str, Any]:
    """面的可視化用のセル値一覧とポリゴン情報を返す。"""
    if metric not in METRIC_WINDOWS:
        raise ValueError(f"未対応の指標です: {metric}")

    with open_db(db_path) as conn:
        selected_dataset_id, candidate_dataset_ids = _resolve_spatial_dataset_id(
            conn,
            polygon_name=polygon_name,
            observed_at=observed_at,
            dataset_id=dataset_id,
        )
        if dataset_id is None and len(candidate_dataset_ids) > 1:
            LOGGER.info(
                "面ビューの dataset_id は時刻一致候補から先頭を採用します: selected=%s candidates=%s",
                selected_dataset_id,
                candidate_dataset_ids,
            )
        grid = _load_dataset_grid(conn, dataset_id=selected_dataset_id)
        polygon_crs, polygon_geometry = _load_polygon_geometry(conn, polygon_name=polygon_name)
        if metric == "1h":
            cells = _load_polygon_cells_for_time(
                conn,
                dataset_id=selected_dataset_id,
                polygon_name=polygon_name,
                observed_at=observed_at,
            ).copy()
            cells["value"] = pd.to_numeric(cells["rainfall_mm"], errors="coerce")
        else:
            cells = _load_polygon_cell_metric_values(
                conn,
                dataset_id=selected_dataset_id,
                polygon_name=polygon_name,
                observed_at=observed_at,
                metric=metric,
            ).copy()

    if cells.empty:
        raise ValueError("指定条件に該当する面表示用セルが見つかりません")

    cells["x_center"] = pd.to_numeric(cells["x_center"], errors="coerce")
    cells["y_center"] = pd.to_numeric(cells["y_center"], errors="coerce")
    cells["polygon_local_row"] = pd.to_numeric(cells["polygon_local_row"], errors="coerce")
    cells["polygon_local_col"] = pd.to_numeric(cells["polygon_local_col"], errors="coerce")
    cells["overlap_ratio"] = pd.to_numeric(cells["overlap_ratio"], errors="coerce")
    cells["value"] = pd.to_numeric(cells["value"], errors="coerce")
    raw_minx = cells["x_center"] - float(grid["cell_width"]) / 2.0
    raw_maxx = cells["x_center"] + float(grid["cell_width"]) / 2.0
    raw_miny = cells["y_center"] - float(grid["cell_height"]) / 2.0
    raw_maxy = cells["y_center"] + float(grid["cell_height"]) / 2.0

    cell_geometries = gpd.GeoSeries(
        [box(minx, miny, maxx, maxy) for minx, miny, maxx, maxy in zip(raw_minx, raw_miny, raw_maxx, raw_maxy)],
        crs=str(grid["grid_crs"]) if grid["grid_crs"] else None,
    )
    center_points = gpd.GeoSeries.from_xy(cells["x_center"], cells["y_center"], crs=str(grid["grid_crs"]) if grid["grid_crs"] else None)
    if str(grid["grid_crs"]) != str(polygon_crs):
        cell_geometries = cell_geometries.to_crs(polygon_crs)
        center_points = center_points.to_crs(polygon_crs)

    bounds = cell_geometries.bounds
    cells["minx"] = bounds["minx"].to_numpy()
    cells["miny"] = bounds["miny"].to_numpy()
    cells["maxx"] = bounds["maxx"].to_numpy()
    cells["maxy"] = bounds["maxy"].to_numpy()
    cells["x_center_plot"] = center_points.x.to_numpy()
    cells["y_center_plot"] = center_points.y.to_numpy()

    combined_bounds = cell_geometries.total_bounds
    poly_bounds = polygon_geometry.bounds
    view_bounds = {
        "minx": float(min(combined_bounds[0], poly_bounds[0])),
        "miny": float(min(combined_bounds[1], poly_bounds[1])),
        "maxx": float(max(combined_bounds[2], poly_bounds[2])),
        "maxy": float(max(combined_bounds[3], poly_bounds[3])),
    }

    return {
        "dataset_id": selected_dataset_id,
        "candidate_dataset_ids": candidate_dataset_ids,
        "polygon_name": polygon_name,
        "polygon_crs": polygon_crs,
        "polygon_geometry": polygon_geometry,
        "observed_at": observed_at,
        "metric": metric,
        "cells": cells.sort_values(["polygon_local_row", "polygon_local_col"]).reset_index(drop=True),
        "cell_width": float(grid["cell_width"]),
        "cell_height": float(grid["cell_height"]),
        "value_label": f"{metric} 雨量 (mm)",
        "view_bounds": view_bounds,
    }
