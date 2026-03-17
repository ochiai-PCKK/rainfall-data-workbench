from __future__ import annotations

from pathlib import Path

import geopandas as gpd

from .models import RegionSpec

_NISHI_NAME = "西除川流域"
_HIGASHI_NAME = "東除川流域"
_YAMATO_NAME = "大和川流域界"

_REGION_MAP = {
    "nishiyoke": _NISHI_NAME,
    "higashiyoke": _HIGASHI_NAME,
}


def _find_polygon_file(root: Path, stem: str) -> Path:
    for suffix in (".gpkg", ".shp"):
        path = root / f"{stem}{suffix}"
        if path.exists():
            return path
    raise FileNotFoundError(f"ポリゴンが見つかりません: {stem}")


def _load_single(path: Path):
    gdf = gpd.read_file(path)
    if gdf.empty:
        raise ValueError(f"空のポリゴンです: {path}")
    if gdf.crs is None:
        raise ValueError(f"CRS が未設定です: {path}")
    if str(gdf.crs).upper() != "EPSG:6674":
        gdf = gdf.to_crs("EPSG:6674")
    return gdf.geometry.union_all()


def load_region_specs(polygon_dir: str | Path) -> list[RegionSpec]:
    """領域仕様を返す（西除川・東除川・結合は必須、大和川は任意）。"""
    root = Path(polygon_dir)
    if not root.exists():
        raise FileNotFoundError(f"ポリゴンディレクトリが見つかりません: {root}")

    loaded: dict[str, object] = {}
    for region_key, polygon_name in _REGION_MAP.items():
        loaded[region_key] = _load_single(_find_polygon_file(root, polygon_name))

    nishi = loaded["nishiyoke"]
    higashi = loaded["higashiyoke"]
    merged = nishi.union(higashi)

    specs: list[RegionSpec] = []
    for key in ("nishiyoke", "higashiyoke"):
        geom = loaded[key]
        specs.append(
            RegionSpec(
                region_key=key,
                region_name=_REGION_MAP[key],
                geometry_6674=geom,
                bbox_6674=geom.bounds,
            )
        )
    specs.append(
        RegionSpec(
            region_key="nishiyoke_higashiyoke",
            region_name="西除川+東除川",
            geometry_6674=merged,
            bbox_6674=merged.bounds,
        )
    )

    # 大和川は任意。存在する場合のみ追加する。
    try:
        yamatogawa_geom = _load_single(_find_polygon_file(root, _YAMATO_NAME))
    except FileNotFoundError:
        yamatogawa_geom = None
    if yamatogawa_geom is not None:
        specs.append(
            RegionSpec(
                region_key="yamatogawa",
                region_name=_YAMATO_NAME,
                geometry_6674=yamatogawa_geom,
                bbox_6674=yamatogawa_geom.bounds,
            )
        )
    return specs
