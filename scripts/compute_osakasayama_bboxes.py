from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd


INPUT_DIR = Path("data/大阪狭山市_流域界再投影")
OUTPUT_PATH = INPUT_DIR / "bbox_summary.txt"

LAYER_FILES = {
    "大和川流域": INPUT_DIR / "大和川流域.gpkg",
    "東除川流域": INPUT_DIR / "東除川流域.gpkg",
    "西除川流域": INPUT_DIR / "西除川流域.gpkg",
}


def _format_bounds(bounds: tuple[float, float, float, float]) -> str:
    minx, miny, maxx, maxy = bounds
    return (
        f"min_lon={minx:.8f}, min_lat={miny:.8f}, "
        f"max_lon={maxx:.8f}, max_lat={maxy:.8f}"
    )


def _read_single_layer(path: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    if gdf.empty:
        raise ValueError(f"No geometries found: {path}")
    if gdf.crs is None:
        raise ValueError(f"CRS is missing: {path}")
    if str(gdf.crs).upper() != "EPSG:4326":
        raise ValueError(f"Expected EPSG:4326, got {gdf.crs}: {path}")
    return gdf


def main() -> None:
    layers: dict[str, gpd.GeoDataFrame] = {
        name: _read_single_layer(path) for name, path in LAYER_FILES.items()
    }

    lines: list[str] = []
    lines.append("BBox summary for data/大阪狭山市_流域界再投影")
    lines.append("CRS: EPSG:4326")
    lines.append("")

    for name, gdf in layers.items():
        bounds = tuple(gdf.total_bounds.tolist())
        lines.append(f"[{name}]")
        lines.append(f"source={LAYER_FILES[name].name}")
        lines.append(_format_bounds(bounds))
        lines.append("")

    combined = gpd.GeoSeries(
        pd.concat(
            [layers["東除川流域"].geometry, layers["西除川流域"].geometry],
            ignore_index=True,
        ),
        crs=layers["東除川流域"].crs,
    )
    combined_bounds = tuple(combined.total_bounds.tolist())

    lines.append("[東除川流域 + 西除川流域]")
    lines.append("source=東除川流域.gpkg + 西除川流域.gpkg")
    lines.append(_format_bounds(combined_bounds))
    lines.append("")

    OUTPUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
