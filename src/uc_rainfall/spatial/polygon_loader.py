from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import wkt as shapely_wkt

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

    combined_geometry = gpd.GeoSeries(
        pd.concat([left.geometry, right.geometry], ignore_index=True),
        crs=left.crs,
    ).union_all()
    combined_frame = gpd.GeoDataFrame({"geometry": [combined_geometry]}, crs=left.crs)
    minx, miny, maxx, maxy = combined_geometry.bounds
    record = PolygonRecord(
        polygon_id=COMBINED_POLYGON_NAME,
        polygon_name=COMBINED_POLYGON_NAME,
        polygon_group="derived",
        polygon_crs=left_crs,
        minx=minx,
        miny=miny,
        maxx=maxx,
        maxy=maxy,
        geometry_wkt=combined_geometry.wkt,
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
        geometry = gdf.geometry.union_all()
        minx, miny, maxx, maxy = geometry.bounds
        normalized = gpd.GeoDataFrame({"geometry": [geometry]}, crs=gdf.crs)
        record = PolygonRecord(
            polygon_id=polygon_name,
            polygon_name=polygon_name,
            polygon_group=None,
            polygon_crs=str(gdf.crs) if gdf.crs else "UNKNOWN",
            minx=minx,
            miny=miny,
            maxx=maxx,
            maxy=maxy,
            geometry_wkt=geometry.wkt,
            file_path=str(path),
        )
        records.append(record)
        frames[polygon_name] = normalized

    combined = _build_combined_polygon(frames, root)
    if combined is not None:
        combined_record, combined_frame = combined
        records.append(combined_record)
        frames[combined_record.polygon_id] = combined_frame

    if not records:
        raise ValueError(f"有効なポリゴンが見つかりません: {root}")
    return records, frames


def load_polygons_from_db(conn) -> tuple[list[PolygonRecord], dict[str, gpd.GeoDataFrame]]:
    """DB に登録済みのポリゴンを復元する。"""
    rows = conn.execute(
        """
        SELECT polygon_id, polygon_name, polygon_group, polygon_crs, minx, miny, maxx, maxy, geometry_wkt, file_path
        FROM polygons
        ORDER BY polygon_name
        """
    ).fetchall()
    if not rows:
        raise ValueError("DB に利用可能なポリゴンが登録されていません。--polygon-dir を指定してください。")

    records: list[PolygonRecord] = []
    frames: dict[str, gpd.GeoDataFrame] = {}
    for row in rows:
        record = PolygonRecord(
            polygon_id=row["polygon_id"],
            polygon_name=row["polygon_name"],
            polygon_group=row["polygon_group"],
            polygon_crs=row["polygon_crs"],
            minx=row["minx"],
            miny=row["miny"],
            maxx=row["maxx"],
            maxy=row["maxy"],
            geometry_wkt=row["geometry_wkt"],
            file_path=row["file_path"],
        )
        geometry = shapely_wkt.loads(record.geometry_wkt)
        frames[record.polygon_id] = gpd.GeoDataFrame({"geometry": [geometry]}, crs=record.polygon_crs)
        records.append(record)
    return records, frames
