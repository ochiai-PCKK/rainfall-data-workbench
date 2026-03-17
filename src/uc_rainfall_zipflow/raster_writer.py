from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio

from .spatial_clip import NODATA_VALUE, calc_xllcorner_yllcorner


def write_tiff(*, path: Path, data: np.ndarray, transform, crs: str, nodata: float | None = NODATA_VALUE) -> None:
    """領域切り出し TIFF を保存する。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=int(data.shape[0]),
        width=int(data.shape[1]),
        count=1,
        dtype="float32",
        crs=crs,
        transform=transform,
        nodata=nodata,
    ) as dst:
        dst.write(data.astype(np.float32, copy=False), 1)


def write_asc(*, path: Path, data: np.ndarray, transform) -> None:
    """Arc/ASCII 形式の ASC を保存する。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows, cols = data.shape
    dx = abs(float(transform.a))
    dy = abs(float(transform.e))
    xllcorner, yllcorner = calc_xllcorner_yllcorner(transform, rows, cols)
    header = [
        f"ncols         {cols}",
        f"nrows         {rows}",
        f"xllcorner     {xllcorner:.6f}",
        f"yllcorner     {yllcorner:.6f}",
        f"DX            {dx:.8f}",
        f"DY            {dy:.8f}",
        f"NODATA_value  {NODATA_VALUE:.0f}",
    ]
    with path.open("w", encoding="utf-8") as fp:
        fp.write("\n".join(header))
        fp.write("\n")
        for row in data:
            values = " ".join(f"{float(v):.3f}" for v in row.tolist())
            fp.write(values)
            fp.write("\n")


def write_dat(*, path: Path, data: np.ndarray, transform) -> None:
    """後方互換: 旧呼び出しを ASC 書き込みへ委譲する。"""
    write_asc(path=path, data=data, transform=transform)


def write_rain_dat_blocks(
    *,
    path: Path,
    frames: list[np.ndarray],
    elapsed_seconds: list[int],
) -> None:
    """rain.dat 互換の時間ブロック形式で保存する。"""
    if len(frames) != len(elapsed_seconds):
        raise ValueError("rain.dat 出力のフレーム数と時刻数が一致しません。")
    if not frames:
        raise ValueError("rain.dat 出力対象が空です。")

    rows, cols = frames[0].shape
    for frame in frames:
        if frame.shape != (rows, cols):
            raise ValueError("rain.dat 出力対象の格子サイズが時刻間で一致しません。")

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        for elapsed, frame in zip(elapsed_seconds, frames, strict=True):
            fp.write(f"{elapsed} {cols} {rows}\n")
            sanitized = np.where(np.isfinite(frame), frame, 0.0)
            sanitized = np.where(sanitized < 0.0, 0.0, sanitized)
            for row in sanitized:
                values = " ".join(str(float(v)) for v in row.tolist())
                fp.write(values)
                fp.write("\n")
