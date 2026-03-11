from __future__ import annotations

from typing import Iterable

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from ..models import GridDefinition, PolygonRecord


def build_polygon_cell_map(
    grid: GridDefinition,
    polygons: list[PolygonRecord],
    polygon_frames: dict[str, gpd.GeoDataFrame],
) -> Iterable[tuple[str, int, int, int, int, float, float, float, int, str]]:
    """セルポリゴンと流域ポリゴンの接触判定から流域-セル対応表を構築する。"""
    cells = []
    for row_index in range(grid.rows):
        y_max = grid.origin_y + grid.cell_height * (grid.rows - row_index)
        y_min = y_max - grid.cell_height
        for col_index in range(grid.cols):
            x_min = grid.origin_x + grid.cell_width * col_index
            x_max = x_min + grid.cell_width
            x_center = x_min + grid.cell_width / 2.0
            y_center = y_min + grid.cell_height / 2.0
            cells.append((row_index, col_index, x_center, y_center, box(x_min, y_min, x_max, y_max)))

    cell_frame = pd.DataFrame(cells, columns=["row", "col", "x_center", "y_center", "geometry"])
    cell_gdf = gpd.GeoDataFrame(
        cell_frame,
        geometry="geometry",
        crs=grid.grid_crs,
    )
    transformed_cells: dict[str, gpd.GeoDataFrame] = {}

    for polygon in polygons:
        polygon_crs = polygon.polygon_crs
        if polygon_crs not in transformed_cells:
            transformed_cells[polygon_crs] = cell_gdf.to_crs(polygon_crs)
        candidate_gdf = transformed_cells[polygon_crs]

        bbox_mask = (
            (candidate_gdf.geometry.bounds["maxx"] >= polygon.minx)
            & (candidate_gdf.geometry.bounds["minx"] <= polygon.maxx)
            & (candidate_gdf.geometry.bounds["maxy"] >= polygon.miny)
            & (candidate_gdf.geometry.bounds["miny"] <= polygon.maxy)
        )
        candidates = candidate_gdf.loc[bbox_mask]
        if candidates.empty:
            continue
        geometry = polygon_frames[polygon.polygon_id].union_all()
        selected = candidates.loc[candidates.geometry.intersects(geometry)].copy()
        if selected.empty:
            continue
        selected["cell_area"] = selected.geometry.area
        selected["overlap_area"] = selected.geometry.intersection(geometry).area
        selected["overlap_ratio"] = selected["overlap_area"] / selected["cell_area"]
        source_rows = {int(value): idx for idx, value in enumerate(sorted(selected["row"].astype(int).unique().tolist()))}
        source_cols = {int(value): idx for idx, value in enumerate(sorted(selected["col"].astype(int).unique().tolist()))}
        selected = selected.sort_values(["row", "col"]).reset_index(drop=True)
        for item in selected.itertuples(index=False):
            row_value = int(item.row)
            col_value = int(item.col)
            yield (
                polygon.polygon_id,
                row_value,
                col_value,
                source_rows[row_value],
                source_cols[col_value],
                float(item.cell_area),
                float(item.overlap_area),
                float(item.overlap_ratio),
                1,
                "cell_intersects_polygon",
            )
