from __future__ import annotations

from typing import Iterable

import geopandas as gpd
import pandas as pd

from ..models import GridDefinition, PolygonRecord


def build_polygon_cell_map(
    grid: GridDefinition,
    polygons: list[PolygonRecord],
    polygon_frames: dict[str, gpd.GeoDataFrame],
) -> Iterable[tuple[str, int, int, int, str]]:
    """セル中心点とポリゴンの包含判定から流域-セル対応表を構築する。"""
    cells = []
    for row_index in range(grid.rows):
        y_center = grid.origin_y + grid.cell_height * (grid.rows - row_index - 0.5)
        for col_index in range(grid.cols):
            x_center = grid.origin_x + grid.cell_width * (col_index + 0.5)
            cells.append((row_index, col_index, x_center, y_center))

    cell_frame = pd.DataFrame(cells, columns=["row", "col", "x_center", "y_center"])
    cell_gdf = gpd.GeoDataFrame(
        cell_frame,
        geometry=gpd.points_from_xy(cell_frame["x_center"], cell_frame["y_center"]),
        crs=grid.grid_crs,
    )
    transformed_cells: dict[str, gpd.GeoDataFrame] = {}

    for polygon in polygons:
        polygon_crs = polygon.polygon_crs
        if polygon_crs not in transformed_cells:
            transformed_cells[polygon_crs] = cell_gdf.to_crs(polygon_crs)
        candidate_gdf = transformed_cells[polygon_crs]

        bbox_mask = (
            (candidate_gdf.geometry.x >= polygon.minx)
            & (candidate_gdf.geometry.x <= polygon.maxx)
            & (candidate_gdf.geometry.y >= polygon.miny)
            & (candidate_gdf.geometry.y <= polygon.maxy)
        )
        candidates = candidate_gdf.loc[bbox_mask]
        if candidates.empty:
            continue
        geometry = polygon_frames[polygon.polygon_id].union_all()
        for row in candidates.itertuples(index=False):
            if geometry.covers(row.geometry):
                yield (polygon.polygon_id, int(row.row), int(row.col), 1, "center_in_polygon")
