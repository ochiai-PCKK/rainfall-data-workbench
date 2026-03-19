from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import rasterio
from affine import Affine
from pyproj import Transformer
from rasterio.features import rasterize
from rasterio.transform import array_bounds
from rasterio.warp import Resampling, calculate_default_transform, reproject
from rasterio.windows import Window, from_bounds
from rasterio.windows import transform as window_transform
from shapely.geometry import box
from shapely.ops import transform as shapely_transform
from shapely.prepared import prep

from .models import RegionSpec

NODATA_VALUE = -9999.0


@dataclass(frozen=True)
class RegionRaster:
    data: np.ndarray
    transform: Affine
    crs: str


@dataclass(frozen=True)
class ClipPlan:
    window: Window
    transform: Affine
    mask: np.ndarray | None = None


def read_and_reproject_6674(raster_path):
    """TIFF を読み込み EPSG:6674 へ再投影した配列を返す。"""
    with rasterio.open(raster_path) as src:
        source = src.read(1).astype(np.float32, copy=False)
        src_nodata = src.nodata
        if src_nodata is not None:
            source = np.where(np.isclose(source, src_nodata), NODATA_VALUE, source)

        if src.crs is None:
            raise ValueError(f"CRS が不明な TIFF です: {raster_path}")

        if str(src.crs).upper() == "EPSG:6674":
            arr = np.where(np.isfinite(source), source, NODATA_VALUE).astype(np.float32, copy=False)
            return arr, src.transform, "EPSG:6674"

        dst_transform, dst_w, dst_h = calculate_default_transform(
            src.crs, "EPSG:6674", src.width, src.height, *src.bounds
        )
        dst = np.full((dst_h, dst_w), NODATA_VALUE, dtype=np.float32)
        reproject(
            source=source,
            destination=dst,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs="EPSG:6674",
            src_nodata=src_nodata,
            dst_nodata=NODATA_VALUE,
            resampling=Resampling.nearest,
        )
        dst = np.where(np.isfinite(dst), dst, NODATA_VALUE).astype(np.float32, copy=False)
        return dst, dst_transform, "EPSG:6674"


def read_and_reproject_4326(raster_path):
    """TIFF を読み込み、入力ZIPの格子情報を保った EPSG:4326 配列を返す。"""
    with rasterio.open(raster_path) as src:
        source = src.read(1).astype(np.float32, copy=False)
        src_nodata = src.nodata
        if src_nodata is not None:
            source = np.where(np.isclose(source, src_nodata), 0.0, source)

        if src.crs is None:
            raise ValueError(f"CRS が不明な TIFF です: {raster_path}")

        # 入力ZIP再現を優先し、4326以外は変換せずエラーにする。
        # 変換すると cellsize_x/y や原点が変わる可能性があるため。
        if str(src.crs).upper() != "EPSG:4326":
            raise ValueError(f"入力TIFFのCRSがEPSG:4326ではありません: {src.crs}")

        arr = np.where(np.isfinite(source), source, 0.0).astype(np.float32, copy=False)
        arr = np.where(arr < 0.0, 0.0, arr).astype(np.float32, copy=False)
        return arr, src.transform, "EPSG:4326"


def _intersect_window(bbox, transform: Affine, width: int, height: int) -> Window:
    raw = from_bounds(*bbox, transform=transform)
    row_off = max(0, int(math.floor(raw.row_off)))
    col_off = max(0, int(math.floor(raw.col_off)))
    row_max = min(height, int(math.ceil(raw.row_off + raw.height)))
    col_max = min(width, int(math.ceil(raw.col_off + raw.width)))
    if row_max <= row_off or col_max <= col_off:
        raise ValueError("BBox がラスタ範囲外です。")
    return Window(col_off=col_off, row_off=row_off, width=col_max - col_off, height=row_max - row_off)


def clip_region(
    *,
    full_data: np.ndarray,
    full_transform: Affine,
    region: RegionSpec,
) -> RegionRaster:
    """再投影済みラスタを領域 BBox で切り出し、領域外を NoData 化する。"""
    plan = build_region_clip_plan(
        full_transform=full_transform,
        full_shape=full_data.shape,
        region=region,
    )
    return apply_region_clip(full_data=full_data, plan=plan)


def clip_masked_bbox(
    *,
    full_data: np.ndarray,
    full_transform: Affine,
    bbox: tuple[float, float, float, float],
    geometry,
    out_crs: str,
) -> RegionRaster:
    """任意CRSの BBox+ジオメトリで切り出し、ジオメトリ外を NoData 化する。"""
    plan = build_masked_bbox_clip_plan(
        full_transform=full_transform,
        full_shape=full_data.shape,
        bbox=bbox,
        geometry=geometry,
    )
    return apply_masked_bbox_clip(full_data=full_data, plan=plan, out_crs=out_crs)


def clip_region_bbox(
    *,
    full_data: np.ndarray,
    full_transform: Affine,
    bbox: tuple[float, float, float, float],
) -> RegionRaster:
    """再投影済みラスタを領域 BBox で切り出し、値は 0 以上に正規化する。"""
    plan = build_bbox_clip_plan(
        full_transform=full_transform,
        full_shape=full_data.shape,
        bbox=bbox,
    )
    return apply_bbox_clip(full_data=full_data, plan=plan)


def build_region_clip_plan(
    *,
    full_transform: Affine,
    full_shape: tuple[int, int],
    region: RegionSpec,
) -> ClipPlan:
    height, width = full_shape
    window = _intersect_window(region.bbox_6674, full_transform, width, height)
    sub_transform = window_transform(window, full_transform)
    out_shape = (int(window.height), int(window.width))
    mask = rasterize(
        [(region.geometry_6674, 1)],
        out_shape=out_shape,
        transform=sub_transform,
        fill=0,
        dtype=np.uint8,
        all_touched=True,
    )
    return ClipPlan(window=window, transform=sub_transform, mask=mask)


def apply_region_clip(*, full_data: np.ndarray, plan: ClipPlan) -> RegionRaster:
    if plan.mask is None:
        raise ValueError("region clip plan に mask がありません。")
    sub = full_data[
        int(plan.window.row_off) : int(plan.window.row_off + plan.window.height),
        int(plan.window.col_off) : int(plan.window.col_off + plan.window.width),
    ].copy()
    sub[(plan.mask == 0) | (~np.isfinite(sub))] = NODATA_VALUE
    return RegionRaster(data=sub.astype(np.float32, copy=False), transform=plan.transform, crs="EPSG:6674")


def build_bbox_clip_plan(
    *,
    full_transform: Affine,
    full_shape: tuple[int, int],
    bbox: tuple[float, float, float, float],
) -> ClipPlan:
    height, width = full_shape
    window = _intersect_window(bbox, full_transform, width, height)
    sub_transform = window_transform(window, full_transform)
    return ClipPlan(window=window, transform=sub_transform, mask=None)


def apply_bbox_clip(*, full_data: np.ndarray, plan: ClipPlan) -> RegionRaster:
    sub = full_data[
        int(plan.window.row_off) : int(plan.window.row_off + plan.window.height),
        int(plan.window.col_off) : int(plan.window.col_off + plan.window.width),
    ].copy()
    sub = np.where(np.isfinite(sub), sub, 0.0)
    sub = np.where(sub < 0.0, 0.0, sub)
    return RegionRaster(data=sub.astype(np.float32, copy=False), transform=plan.transform, crs="EPSG:4326")


def build_masked_bbox_clip_plan(
    *,
    full_transform: Affine,
    full_shape: tuple[int, int],
    bbox: tuple[float, float, float, float],
    geometry,
) -> ClipPlan:
    height, width = full_shape
    window = _intersect_window(bbox, full_transform, width, height)
    sub_transform = window_transform(window, full_transform)
    out_shape = (int(window.height), int(window.width))
    mask = rasterize(
        [(geometry, 1)],
        out_shape=out_shape,
        transform=sub_transform,
        fill=0,
        dtype=np.uint8,
        all_touched=True,
    )
    return ClipPlan(window=window, transform=sub_transform, mask=mask)


def apply_masked_bbox_clip(*, full_data: np.ndarray, plan: ClipPlan, out_crs: str) -> RegionRaster:
    if plan.mask is None:
        raise ValueError("masked bbox clip plan に mask がありません。")
    sub = full_data[
        int(plan.window.row_off) : int(plan.window.row_off + plan.window.height),
        int(plan.window.col_off) : int(plan.window.col_off + plan.window.width),
    ].copy()
    sub[(plan.mask == 0) | (~np.isfinite(sub))] = NODATA_VALUE
    return RegionRaster(data=sub.astype(np.float32, copy=False), transform=plan.transform, crs=out_crs)


def validate_region_alignment(reference: RegionRaster, candidate: RegionRaster) -> None:
    """時刻間で切り出し格子が一致しているか確認する。"""
    if reference.data.shape != candidate.data.shape:
        raise ValueError("時刻間で切り出し格子サイズが一致しません。")
    ref = reference.transform
    cur = candidate.transform
    tol = 1e-6
    for lhs, rhs in ((ref.a, cur.a), (ref.e, cur.e), (ref.c, cur.c), (ref.f, cur.f)):
        if abs(lhs - rhs) > tol:
            raise ValueError("時刻間で切り出し格子の transform が一致しません。")


def is_grid_compatible_by_bounds(
    reference: RegionRaster,
    candidate: RegionRaster,
    *,
    bounds_tol: float = 1e-6,
    res_tol: float = 1e-9,
) -> bool:
    """矩形境界・格子サイズ・解像度の一致で互換判定する。"""
    if reference.data.shape != candidate.data.shape:
        return False

    ref_dx = abs(reference.transform.a)
    ref_dy = abs(reference.transform.e)
    cur_dx = abs(candidate.transform.a)
    cur_dy = abs(candidate.transform.e)
    if abs(ref_dx - cur_dx) > res_tol or abs(ref_dy - cur_dy) > res_tol:
        return False

    ref_bounds = array_bounds(reference.data.shape[0], reference.data.shape[1], reference.transform)
    cur_bounds = array_bounds(candidate.data.shape[0], candidate.data.shape[1], candidate.transform)
    return all(abs(lhs - rhs) <= bounds_tol for lhs, rhs in zip(ref_bounds, cur_bounds, strict=True))


def align_region_raster_to_reference(candidate: RegionRaster, reference: RegionRaster) -> RegionRaster:
    """候補ラスタを基準ラスタ格子へ再配置する。"""
    dst = np.full(reference.data.shape, NODATA_VALUE, dtype=np.float32)
    reproject(
        source=candidate.data.astype(np.float32, copy=False),
        destination=dst,
        src_transform=candidate.transform,
        src_crs=candidate.crs,
        dst_transform=reference.transform,
        dst_crs=reference.crs,
        src_nodata=NODATA_VALUE,
        dst_nodata=NODATA_VALUE,
        resampling=Resampling.nearest,
    )
    return RegionRaster(data=dst, transform=reference.transform, crs=reference.crs)


def build_overlap_weights(region_raster: RegionRaster, region_geometry) -> np.ndarray:
    """領域内重み（セル面積に対する交差比）を計算する。"""
    arr = region_raster.data
    transform = region_raster.transform
    rows, cols = arr.shape
    cell_area = abs(transform.a * transform.e)
    if cell_area <= 0:
        raise ValueError("セル面積が不正です。")

    prepared = prep(region_geometry)
    weights = np.zeros((rows, cols), dtype=np.float64)
    for r in range(rows):
        for c in range(cols):
            x_left = transform.c + (c * transform.a)
            x_right = x_left + transform.a
            y_top = transform.f + (r * transform.e)
            y_bottom = y_top + transform.e
            cell = box(min(x_left, x_right), min(y_top, y_bottom), max(x_left, x_right), max(y_top, y_bottom))
            if not prepared.intersects(cell):
                continue
            inter_area = region_geometry.intersection(cell).area
            if inter_area <= 0:
                continue
            weights[r, c] = min(1.0, inter_area / cell_area)
    return weights


def compute_weighted_sum(data: np.ndarray, weights: np.ndarray) -> float:
    """NoData を除外した重み付き合計を計算する。"""
    valid = (data != NODATA_VALUE) & (weights > 0.0) & np.isfinite(data)
    if not np.any(valid):
        return float("nan")
    return float(np.sum(data[valid] * weights[valid]))


def calc_xllcorner_yllcorner(transform: Affine, rows: int, cols: int) -> tuple[float, float]:
    """Arc/ASCII 互換ヘッダ用に左下座標を計算する。"""
    west, south, _, _ = array_bounds(rows, cols, transform)
    return float(west), float(south)


def transform_geometry(geometry, *, src_crs: str, dst_crs: str):
    """ジオメトリを CRS 変換する。"""
    transformer = Transformer.from_crs(src_crs, dst_crs, always_xy=True)
    return shapely_transform(transformer.transform, geometry)
