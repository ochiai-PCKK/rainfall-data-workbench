from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Iterable

import rasterio

from ..models import GridDefinition

MAIL_PATTERNS = {
    "origin_x": re.compile(r"xll\s*:\s*([0-9.+-]+)"),
    "origin_y": re.compile(r"yll\s*:\s*([0-9.+-]+)"),
    "cell_width": re.compile(r"cellsize_x\s*:\s*([0-9.+-]+)"),
    "cell_height": re.compile(r"cellsize_y\s*:\s*([0-9.+-]+)"),
}


def build_grid_definition(
    dataset_id: str,
    rows: int,
    cols: int,
    mail_text_path: Path | None,
    raster_paths: tuple[Path, ...],
    *,
    grid_crs: str = "EPSG:4326",
) -> GridDefinition:
    """メール本文または TIFF メタ情報から格子定義を組み立てる。"""
    values: dict[str, float] | None = None
    if mail_text_path is not None and mail_text_path.exists():
        text = mail_text_path.read_text(encoding="utf-8")
        values = {}
        for key, pattern in MAIL_PATTERNS.items():
            match = pattern.search(text)
            if match is None:
                raise ValueError(f"メール本文に {key} がありません: {mail_text_path}")
            values[key] = float(match.group(1))
    elif raster_paths:
        with rasterio.open(raster_paths[0]) as src:
            left, bottom, right, top = src.bounds
            values = {
                "origin_x": float(left),
                "origin_y": float(bottom),
                "cell_width": float((right - left) / src.width),
                "cell_height": float((top - bottom) / src.height),
            }
            if src.width != cols or src.height != rows:
                raise ValueError(
                    f"TIFF と rain.dat の格子サイズが一致しません: "
                    f"raster=({src.height},{src.width}) rain.dat=({rows},{cols})"
                )
            if src.crs:
                grid_crs = str(src.crs)
    else:
        raise FileNotFoundError("格子定義の取得には mail_txt.txt または TIFF が最低1件必要です。")

    return GridDefinition(
        dataset_id=dataset_id,
        grid_crs=grid_crs,
        origin_x=values["origin_x"],  # type: ignore[index]
        origin_y=values["origin_y"],  # type: ignore[index]
        cell_width=values["cell_width"],  # type: ignore[index]
        cell_height=values["cell_height"],  # type: ignore[index]
        rows=rows,
        cols=cols,
    )


def iter_cell_rows(
    observed_times: list[datetime],
    matrices: list[list[list[float]]],
    grid: GridDefinition,
) -> Iterable[tuple[str, int, int, float, float, float | None]]:
    """行列データを DB 登録用のセル時系列レコードへ展開する。"""
    if len(observed_times) != len(matrices):
        raise ValueError(f"観測時刻数と行列ブロック数が一致しません: {len(observed_times)} != {len(matrices)}")

    for observed_at, matrix in zip(observed_times, matrices):
        if len(matrix) != grid.rows:
            raise ValueError(f"行数が格子定義と一致しません: {len(matrix)} != {grid.rows}")
        for row_index, row_values in enumerate(matrix):
            if len(row_values) != grid.cols:
                raise ValueError(f"列数が格子定義と一致しません: row={row_index} {len(row_values)} != {grid.cols}")

            y_center = grid.origin_y + grid.cell_height * (grid.rows - row_index - 0.5)
            for col_index, rainfall_mm in enumerate(row_values):
                x_center = grid.origin_x + grid.cell_width * (col_index + 0.5)
                yield (
                    observed_at.isoformat(timespec="seconds"),
                    row_index,
                    col_index,
                    x_center,
                    y_center,
                    rainfall_mm,
                )
