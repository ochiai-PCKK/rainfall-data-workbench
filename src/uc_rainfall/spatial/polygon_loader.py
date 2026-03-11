from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd

from ..models import PolygonRecord

COMBINED_POLYGON_NAME = "東除川流域 + 西除川流域"
COMBINED_COMPONENTS = ("東除川流域", "西除川流域")


def _build_combined_polygon(
    frames: dict[str, gpd.GeoDataFrame],
    root: Path,
) -> tuple[PolygonRecord, gpd.GeoDataFrame] | None:
    """東除川と西除川を結合した派生ポリゴンを構築する。"""
    if not all(name in frames for name in COMBINED_COMPONENTS):
        return None

    left = frames[COMBINED_COMPONENTS[0]]
    right = frames[COMBINED_COMPONENTS[1]]
    left_crs = str(left.crs) if left.crs else "UNKNOWN"
    right_crs = str(right.crs) if right.crs else "UNKNOWN"
    if left_crs != right_crs:
        raise ValueError(
            f"CRS が異なるため結合できません: {COMBINED_COMPONENTS[0]}={left_crs}, {COMBINED_COMPONENTS[1]}={right_crs}"
        )

    combined_frame = gpd.GeoDataFrame(
        pd.concat([left, right], ignore_index=True),
        crs=left.crs,
    )
    minx, miny, maxx, maxy = combined_frame.total_bounds.tolist()
    record = PolygonRecord(
        polygon_id=COMBINED_POLYGON_NAME,
        polygon_name=COMBINED_POLYGON_NAME,
        polygon_group="derived",
        polygon_crs=left_crs,
        minx=minx,
        miny=miny,
        maxx=maxx,
        maxy=maxy,
        file_path=str(root),
    )
    return record, combined_frame


def load_polygons(polygon_dir: str | Path) -> tuple[list[PolygonRecord], dict[str, gpd.GeoDataFrame]]:
    """ポリゴン群を読み込み、必要なら派生ポリゴンも追加する。"""
    root = Path(polygon_dir)
    if not root.exists():
        raise FileNotFoundError(f"ポリゴンディレクトリが見つかりません: {root}")

    polygon_paths = sorted(root.glob("*.gpkg")) + sorted(root.glob("*.shp"))
    if not polygon_paths:
        raise ValueError(f"ポリゴンファイルが見つかりません: {root}")

    records: list[PolygonRecord] = []
    frames: dict[str, gpd.GeoDataFrame] = {}
    for path in polygon_paths:
        polygon_name = path.stem
        if polygon_name in frames:
            continue
        gdf = gpd.read_file(path)
        if gdf.empty:
            continue
        minx, miny, maxx, maxy = gdf.total_bounds.tolist()
        record = PolygonRecord(
            polygon_id=polygon_name,
            polygon_name=polygon_name,
            polygon_group=None,
            polygon_crs=str(gdf.crs) if gdf.crs else "UNKNOWN",
            minx=minx,
            miny=miny,
            maxx=maxx,
            maxy=maxy,
            file_path=str(path),
        )
        records.append(record)
        frames[polygon_name] = gdf

    combined = _build_combined_polygon(frames, root)
    if combined is not None:
        combined_record, combined_frame = combined
        records.append(combined_record)
        frames[combined_record.polygon_id] = combined_frame

    if not records:
        raise ValueError(f"有効なポリゴンが見つかりません: {root}")
    return records, frames
