# pyright: reportArgumentType=false, reportAssignmentType=false
from __future__ import annotations

from datetime import datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from rasterio.warp import transform_bounds

from .errors import ZipFlowError
from .graph_builder import (
    build_metric_frame,
    find_metric_peaks,
    render_region_plots,
    render_region_plots_reference,
)
from .graph_renderer_reference import compute_axis_tops, prepare_reference_window
from .logger import build_logger
from .models import RegionSpec, RunConfig, ZipWindow
from .raster_writer import write_asc, write_rain_dat_blocks, write_tiff
from .regions import load_region_specs
from .runtime_engine import compute_weighted_stats
from .spatial_clip import (
    NODATA_VALUE,
    ClipPlan,
    RegionRaster,
    apply_bbox_clip,
    apply_masked_bbox_clip,
    apply_region_clip,
    build_bbox_clip_plan,
    build_masked_bbox_clip_plan,
    build_overlap_weights,
    build_region_clip_plan,
    read_and_reproject_4326,
    read_and_reproject_6674,
    transform_geometry,
    validate_region_alignment,
)
from .style_profile import load_style_profile
from .time_series_builder import build_hourly_slots
from .zip_reader import build_raster_index, extract_target_zips, resolve_slot_rasters
from .zip_selector import select_target_zips, select_target_zips_from_windows


def _resolve_window_range(config: RunConfig) -> tuple[datetime, datetime]:
    if config.window_mode == "offset":
        if config.days_before < 0 or config.days_after < 0:
            raise ZipFlowError("--days-before/--days-after は 0 以上で指定してください。", exit_code=2)
        start = datetime.combine(config.base_date - timedelta(days=config.days_before), time(hour=0))
        end = datetime.combine(config.base_date + timedelta(days=config.days_after), time(hour=23))
        return start, end

    if config.window_mode != "range":
        raise ZipFlowError(f"未対応の window_mode です: {config.window_mode}", exit_code=2)
    if config.start_date is None or config.end_date is None:
        raise ZipFlowError("window-mode=range では --start-date と --end-date が必須です。", exit_code=2)
    if config.end_date < config.start_date:
        raise ZipFlowError("--end-date は --start-date 以降を指定してください。", exit_code=2)
    start = datetime.combine(config.start_date, time(hour=0))
    end = datetime.combine(config.end_date, time(hour=23))
    return start, end


def _prepare_outputs(config: RunConfig) -> tuple[Path, Path, Path, Path, Path, Path]:
    base_dir = config.output_root / config.base_date.strftime("%Y-%m-%d")
    raster_dir = base_dir / "raster"
    raster_bbox_dir = base_dir / "raster_bbox"
    plot_dir = base_dir / "plots"
    plot_ref_dir = config.output_root / "plots_reference"
    csv_dir = base_dir / "analysis_csv"
    log_dir = base_dir / "logs"
    if "raster" in config.output_kinds:
        raster_dir.mkdir(parents=True, exist_ok=True)
    if "raster_bbox" in config.output_kinds:
        raster_bbox_dir.mkdir(parents=True, exist_ok=True)
    if "plots" in config.output_kinds:
        plot_dir.mkdir(parents=True, exist_ok=True)
    if "plots_ref" in config.output_kinds:
        plot_ref_dir.mkdir(parents=True, exist_ok=True)
    if "timeseries_csv" in config.output_kinds:
        csv_dir.mkdir(parents=True, exist_ok=True)
    if config.enable_log:
        log_dir.mkdir(parents=True, exist_ok=True)
    return raster_dir, raster_bbox_dir, plot_dir, plot_ref_dir, csv_dir, log_dir


def _required_coverage_ok(*, selected, window_start: datetime, window_end: datetime) -> bool:
    """選定 ZIP の期間で対象5日を連続被覆できるか簡易判定する。"""
    pointer = window_start
    for item in sorted(selected, key=lambda z: z.start_at):
        if item.end_at < pointer:
            continue
        if item.start_at > pointer:
            return False
        pointer = max(pointer, item.end_at + timedelta(hours=1))
        if pointer > window_end:
            return True
    return pointer > window_end


def _write_timeseries_csv_readme(
    *,
    csv_dir: Path,
    base_date,
    region_keys: list[str],
    window_start: datetime,
    window_end: datetime,
    slot_count: int,
) -> Path:
    readme_path = csv_dir / "README_ja.txt"
    text = (
        "UC Rainfall ZIP Flow - analysis_csv 説明\n"
        "\n"
        f"基準日: {base_date:%Y-%m-%d}\n"
        f"対象流域: {', '.join(region_keys)}\n"
        f"対象期間: {window_start:%Y-%m-%d %H:%M:%S} 〜 {window_end:%Y-%m-%d %H:%M:%S} (JST)\n"
        f"時系列点数: {slot_count} (1時間間隔)\n"
        "\n"
        "各CSVの列定義:\n"
        "- observed_at_jst: 観測時刻（JST, YYYY-MM-DD HH:MM:SS）\n"
        "- elapsed_seconds: 基準期間先頭からの経過秒\n"
        "- weighted_sum_mm: 重み付き合計雨量 [mm]\n"
        "- valid_weight: 有効セルの重み合計（欠損除外後）\n"
        "- total_weight: 流域内理論重み合計（欠損除外前）\n"
        "- valid_cell_count: 有効セル数（重み>0 かつ欠損でないセル）\n"
        "- total_cell_count: 対象セル数（重み>0 のセル）\n"
        "- coverage_ratio: valid_weight / total_weight\n"
        "- weighted_mean_mm: 重み付き平均雨量 [mm] = weighted_sum_mm / valid_weight\n"
        "\n"
        "流域セルCSV（*_cells.csv）の列定義:\n"
        "- local_row, local_col: 切り出し後のローカル行列番号\n"
        "- center_x_6674, center_y_6674: セル中心座標（EPSG:6674）\n"
        "- cell_weight: 流域との重なり比（0〜1）\n"
        "- cell_area_6674: セル面積（EPSG:6674 座標系上）\n"
        "\n"
        "補足:\n"
        "- ポリゴン境界で切れるセルは、交差面積比（0〜1）を重みとして計算します。\n"
        "- coverage_ratio < 0.999 の時刻がある場合はエラーとして処理を中断します。\n"
        "- weighted_mean_mm は再計算可能です（weighted_sum_mm ÷ valid_weight）。\n"
        "- *_cells.csv は先頭時刻の格子で作成します。\n"
    )
    readme_path.write_text(text, encoding="utf-8")
    return readme_path


GridSignature = tuple[tuple[int, int], tuple[float, float, float, float, float, float]]
WeightCacheEntry = tuple[GridSignature, np.ndarray, np.ndarray, float, int]


def _grid_signature(region_raster: RegionRaster) -> GridSignature:
    tfm = region_raster.transform
    return region_raster.data.shape, (tfm.a, tfm.b, tfm.c, tfm.d, tfm.e, tfm.f)


def _array_signature(data: np.ndarray, transform) -> GridSignature:
    return data.shape, (transform.a, transform.b, transform.c, transform.d, transform.e, transform.f)


def _build_cell_catalog_rows(region_raster: RegionRaster, weights: np.ndarray) -> list[dict[str, float | int]]:
    rows: list[dict[str, float | int]] = []
    cell_area = abs(region_raster.transform.a * region_raster.transform.e)
    nrows, ncols = region_raster.data.shape
    for r in range(nrows):
        for c in range(ncols):
            weight = float(weights[r, c])
            if weight <= 0.0:
                continue
            center_x, center_y = region_raster.transform * (c + 0.5, r + 0.5)
            rows.append(
                {
                    "local_row": r,
                    "local_col": c,
                    "center_x_6674": float(center_x),
                    "center_y_6674": float(center_y),
                    "cell_weight": weight,
                    "cell_area_6674": float(cell_area),
                }
            )
    return rows


def _build_reference_axis_tops_for_run(
    *,
    frame_sum: pd.DataFrame,
    frame_mean: pd.DataFrame,
    base_date,
    graph_spans: tuple[str, ...],
    ref_graph_kinds: tuple[str, ...],
    left_top_default: float,
    right_top_default: float,
) -> dict[tuple[str, str], tuple[float, float]]:
    axis_tops: dict[tuple[str, str], tuple[float, float]] = {}
    for span in graph_spans:
        span_days = 3 if span == "3d" else 5
        center = datetime.combine(base_date, time(hour=0))
        start = center - timedelta(days=span_days // 2)
        end = start + timedelta(hours=(span_days * 24) - 1)
        for kind in ref_graph_kinds:
            frame_src = frame_sum if kind == "sum" else frame_mean
            span_frame = frame_src[(frame_src["observed_at"] >= start) & (frame_src["observed_at"] <= end)]
            window = prepare_reference_window(span_frame)
            left_max = float(window["rainfall_mm"].max())
            right_max = float(window["cumulative_mm"].max())
            axis_tops[(span, kind)] = compute_axis_tops(
                left_max=left_max,
                right_max=right_max,
                left_top_default=left_top_default,
                right_top_default=right_top_default,
            )
    return axis_tops


def run_zipflow(
    config: RunConfig,
    *,
    prelisted_windows: list[ZipWindow] | None = None,
    preloaded_regions: list[RegionSpec] | None = None,
    shared_axis_tops_by_region: dict[str, dict[tuple[str, str], tuple[float, float]]] | None = None,
    collect_axis_tops_only: bool = False,
    collect_metric_frames: bool = False,
) -> dict[str, object]:
    """ZIP Flow 実行本体。"""
    raster_dir, raster_bbox_dir, plot_dir, plot_ref_dir, csv_dir, log_dir = _prepare_outputs(config)
    log_path = log_dir / f"{config.base_date:%Y-%m-%d}.log"
    reference_base_date = config.reference_base_date or config.base_date
    logger = build_logger(enable_file=config.enable_log, log_path=log_path)
    style_profile = None
    if "plots_ref" in config.output_kinds:
        try:
            style_profile = load_style_profile(config.style_profile_path)
        except Exception as exc:  # noqa: BLE001
            raise ZipFlowError(f"スタイルプロファイル読込に失敗しました: {exc}", exit_code=2) from exc

    window_start, window_end = _resolve_window_range(config)
    slots = build_hourly_slots(window_start=window_start, window_end=window_end)
    slot_count = len(slots)
    logger.info("対象期間: %s 〜 %s (%s点)", window_start, window_end, slot_count)

    try:
        if prelisted_windows is None:
            selected = select_target_zips(
                input_zipdir=config.input_zipdir,
                window_start=window_start,
                window_end=window_end,
            )
        else:
            selected = select_target_zips_from_windows(
                windows=prelisted_windows,
                window_start=window_start,
                window_end=window_end,
            )
    except Exception as exc:  # noqa: BLE001
        raise ZipFlowError(f"ZIP 選定に失敗しました: {exc}", exit_code=3) from exc
    logger.info("採用 ZIP: %s", [item.path.name for item in selected])
    if not _required_coverage_ok(selected=selected, window_start=window_start, window_end=window_end):
        raise ZipFlowError("採用 ZIP の期間が対象5日を連続で覆っていません。", exit_code=3)

    try:
        all_regions = preloaded_regions if preloaded_regions is not None else load_region_specs(config.polygon_dir)
    except Exception as exc:  # noqa: BLE001
        raise ZipFlowError(f"空間領域の読込に失敗しました: {exc}", exit_code=6) from exc
    by_key = {region.region_key: region for region in all_regions}
    missing_keys = [key for key in config.region_keys if key not in by_key]
    if missing_keys:
        raise ZipFlowError(f"未定義の region_key が指定されました: {missing_keys}", exit_code=2)
    regions = [by_key[key] for key in config.region_keys]
    geom_4326_by_region = {
        region.region_key: transform_geometry(region.geometry_6674, src_crs="EPSG:6674", dst_crs="EPSG:4326")
        for region in regions
    }
    bbox_4326_by_region = {
        region.region_key: transform_bounds("EPSG:6674", "EPSG:4326", *region.bbox_6674, densify_pts=21)
        for region in regions
    }
    logger.info("領域: %s", [r.region_key for r in regions])

    observed_at = [slot.observed_at_jst for slot in slots]
    enable_any_plot = "plots" in config.output_kinds or "plots_ref" in config.output_kinds
    enable_metric_calc = enable_any_plot or collect_metric_frames
    enable_timeseries_csv = "timeseries_csv" in config.output_kinds
    enable_weight_calc = enable_metric_calc or enable_timeseries_csv
    weighted_series: dict[str, list[float]] = (
        {region.region_key: [] for region in regions} if enable_metric_calc else {}
    )
    weighted_mean_series: dict[str, list[float]] = (
        {region.region_key: [] for region in regions} if enable_metric_calc else {}
    )
    weighted_rows: dict[str, list[dict[str, object]]] = (
        {region.region_key: [] for region in regions} if enable_timeseries_csv else {}
    )
    cell_catalog_rows: dict[str, list[dict[str, float | int]]] = (
        {region.region_key: [] for region in regions} if enable_timeseries_csv else {}
    )
    cell_catalog_signature: dict[str, GridSignature | None] = (
        {region.region_key: None for region in regions} if enable_timeseries_csv else {}
    )
    weight_cache: dict[str, WeightCacheEntry] = {}
    ref_raster_cache: dict[str, RegionRaster] = {}
    ref_bbox_cache: dict[str, RegionRaster] = {}
    bbox_frames: dict[str, list[np.ndarray]] = {region.region_key: [] for region in regions}
    elapsed_seconds = [slot.relative_seconds for slot in slots]
    raster_6674_cache: dict[Path, tuple[np.ndarray, object]] = {}
    raster_4326_cache: dict[Path, tuple[np.ndarray, object]] = {}
    clip_plan_6674_cache: dict[tuple[str, GridSignature], ClipPlan] = {}
    clip_plan_bbox_4326_cache: dict[tuple[str, GridSignature], ClipPlan] = {}
    clip_plan_masked_4326_cache: dict[tuple[str, GridSignature], ClipPlan] = {}

    try:
        with extract_target_zips(selected) as extracted:
            raster_index = build_raster_index(extracted)
            slot_rasters = resolve_slot_rasters(slots=slots, raster_index=raster_index)

            if len(slot_rasters) != slot_count:
                raise ZipFlowError(
                    f"時系列点数が想定と一致しません: expected={slot_count} actual={len(slot_rasters)}",
                    exit_code=5,
                )

            for slot, raster_path in zip(slots, slot_rasters, strict=True):
                arr_6674 = None
                transform_6674 = None
                if enable_weight_calc:
                    cached_6674 = raster_6674_cache.get(raster_path)
                    if cached_6674 is None:
                        arr_6674, transform_6674, _ = read_and_reproject_6674(raster_path)
                        raster_6674_cache[raster_path] = (arr_6674, transform_6674)
                    else:
                        arr_6674, transform_6674 = cached_6674

                arr_4326 = None
                transform_4326 = None
                if "raster_bbox" in config.output_kinds or "raster" in config.output_kinds:
                    cached_4326 = raster_4326_cache.get(raster_path)
                    if cached_4326 is None:
                        arr_4326, transform_4326, _ = read_and_reproject_4326(raster_path)
                        raster_4326_cache[raster_path] = (arr_4326, transform_4326)
                    else:
                        arr_4326, transform_4326 = cached_4326

                for region in regions:
                    clipped = None
                    if enable_weight_calc:
                        assert arr_6674 is not None and transform_6674 is not None
                        sig_6674 = _array_signature(arr_6674, transform_6674)
                        clip_plan_key_6674 = (region.region_key, sig_6674)
                        clip_plan_6674 = clip_plan_6674_cache.get(clip_plan_key_6674)
                        if clip_plan_6674 is None:
                            clip_plan_6674 = build_region_clip_plan(
                                full_transform=transform_6674,
                                full_shape=arr_6674.shape,
                                region=region,
                            )
                            clip_plan_6674_cache[clip_plan_key_6674] = clip_plan_6674
                        clipped = apply_region_clip(full_data=arr_6674, plan=clip_plan_6674)

                    if enable_weight_calc:
                        assert clipped is not None
                        signature = _grid_signature(clipped)
                        cached = weight_cache.get(region.region_key)
                        if cached is None or cached[0] != signature:
                            weights = build_overlap_weights(clipped, region.geometry_6674)
                            positive_mask = weights > 0.0
                            total_weight = float(np.sum(weights))
                            total_cell_count = int(np.count_nonzero(positive_mask))
                            weight_cache[region.region_key] = (
                                signature,
                                weights,
                                positive_mask,
                                total_weight,
                                total_cell_count,
                            )
                        else:
                            _cached_signature, weights, positive_mask, total_weight, total_cell_count = cached
                        if total_weight <= 0.0:
                            raise ZipFlowError(
                                f"流域内重みが0です: region={region.region_key} time={slot.observed_at_jst}",
                                exit_code=5,
                            )
                        valid_mask = (clipped.data != NODATA_VALUE) & np.isfinite(clipped.data) & positive_mask
                        valid_cell_count = int(np.count_nonzero(valid_mask))
                        stats = compute_weighted_stats(data=clipped.data, weights=weights, engine=config.engine)
                        valid_weight = stats.valid_weight
                        coverage = stats.coverage_ratio
                        if coverage < 0.999:
                            raise ZipFlowError(
                                "流域内に欠損（穴）があるため処理を中断しました: "
                                f"region={region.region_key} time={slot.observed_at_jst:%Y-%m-%d %H:%M:%S} "
                                f"coverage={coverage:.6f}",
                                exit_code=5,
                            )

                        weighted_value = stats.weighted_sum
                        if not np.isfinite(weighted_value):
                            detail = f"region={region.region_key} time={slot.observed_at_jst}"
                            raise ZipFlowError(
                                f"重み付き合計を計算できませんでした: {detail}",
                                exit_code=5,
                            )
                        weighted_mean = stats.weighted_mean
                        if enable_metric_calc:
                            weighted_series[region.region_key].append(weighted_value)
                            weighted_mean_series[region.region_key].append(weighted_mean)
                        if enable_timeseries_csv:
                            weighted_rows[region.region_key].append(
                                {
                                    "observed_at_jst": slot.observed_at_jst.strftime("%Y-%m-%d %H:%M:%S"),
                                    "elapsed_seconds": slot.relative_seconds,
                                    "weighted_sum_mm": weighted_value,
                                    "valid_weight": valid_weight,
                                    "total_weight": total_weight,
                                    "valid_cell_count": valid_cell_count,
                                    "total_cell_count": total_cell_count,
                                    "coverage_ratio": coverage,
                                    "weighted_mean_mm": weighted_mean,
                                }
                            )
                            if cell_catalog_signature[region.region_key] is None:
                                cell_catalog_signature[region.region_key] = signature
                                cell_catalog_rows[region.region_key] = _build_cell_catalog_rows(clipped, weights)
                            elif signature != cell_catalog_signature[region.region_key]:
                                logger.warning(
                                    "流域セルCSVは先頭時刻格子で出力します（格子差異あり）: region=%s time=%s",
                                    region.region_key,
                                    slot.observed_at_jst.strftime("%Y-%m-%d %H:%M:%S"),
                                )

                    clipped_bbox = None
                    if "raster_bbox" in config.output_kinds:
                        assert arr_4326 is not None and transform_4326 is not None
                        sig_4326 = _array_signature(arr_4326, transform_4326)
                        clip_plan_key_bbox = (region.region_key, sig_4326)
                        clip_plan_bbox = clip_plan_bbox_4326_cache.get(clip_plan_key_bbox)
                        if clip_plan_bbox is None:
                            clip_plan_bbox = build_bbox_clip_plan(
                                full_transform=transform_4326,
                                full_shape=arr_4326.shape,
                                bbox=bbox_4326_by_region[region.region_key],
                            )
                            clip_plan_bbox_4326_cache[clip_plan_key_bbox] = clip_plan_bbox
                        clipped_bbox = apply_bbox_clip(full_data=arr_4326, plan=clip_plan_bbox)
                        ref_bbox = ref_bbox_cache.get(region.region_key)
                        if ref_bbox is None:
                            ref_bbox_cache[region.region_key] = clipped_bbox
                        else:
                            validate_region_alignment(ref_bbox, clipped_bbox)
                        bbox_frames[region.region_key].append(clipped_bbox.data.copy())

                    clipped_raster = None
                    if "raster" in config.output_kinds:
                        assert arr_4326 is not None and transform_4326 is not None
                        sig_4326 = _array_signature(arr_4326, transform_4326)
                        clip_plan_key_masked = (region.region_key, sig_4326)
                        clip_plan_masked = clip_plan_masked_4326_cache.get(clip_plan_key_masked)
                        if clip_plan_masked is None:
                            clip_plan_masked = build_masked_bbox_clip_plan(
                                full_transform=transform_4326,
                                full_shape=arr_4326.shape,
                                bbox=bbox_4326_by_region[region.region_key],
                                geometry=geom_4326_by_region[region.region_key],
                            )
                            clip_plan_masked_4326_cache[clip_plan_key_masked] = clip_plan_masked
                        clipped_raster = apply_masked_bbox_clip(
                            full_data=arr_4326,
                            plan=clip_plan_masked,
                            out_crs="EPSG:4326",
                        )
                        ref_raster = ref_raster_cache.get(region.region_key)
                        if ref_raster is None:
                            ref_raster_cache[region.region_key] = clipped_raster
                        else:
                            validate_region_alignment(ref_raster, clipped_raster)

                    stamp = slot.observed_at_jst.strftime("%Y%m%d%H")
                    if "raster" in config.output_kinds:
                        assert clipped_raster is not None
                        raster_base = raster_dir / region.region_key
                        tiff_path = raster_base / f"{region.region_key}_{stamp}.tif"
                        asc_path = raster_base / f"{region.region_key}_{stamp}.asc"
                        legacy_dat_path = raster_base / f"{region.region_key}_{stamp}.dat"
                        write_tiff(
                            path=tiff_path,
                            data=clipped_raster.data,
                            transform=clipped_raster.transform,
                            crs=clipped_raster.crs,
                        )
                        write_asc(path=asc_path, data=clipped_raster.data, transform=clipped_raster.transform)
                        if legacy_dat_path.exists():
                            legacy_dat_path.unlink()
                    if "raster_bbox" in config.output_kinds:
                        assert clipped_bbox is not None
                        raster_bbox_base = raster_bbox_dir / region.region_key
                        tiff_bbox_name = f"rain_{region.region_key}_{slot.observed_at_jst:%Y%m%d%H}.tif"
                        write_tiff(
                            path=raster_bbox_base / tiff_bbox_name,
                            data=clipped_bbox.data,
                            transform=clipped_bbox.transform,
                            crs=clipped_bbox.crs,
                            nodata=None,
                        )
    except ZipFlowError:
        raise
    except ValueError as exc:
        message = str(exc)
        if "不足" in message or "時系列" in message:
            raise ZipFlowError(message, exit_code=5) from exc
        if "transform" in message or "BBox" in message or "CRS" in message:
            raise ZipFlowError(message, exit_code=6) from exc
        raise ZipFlowError(f"データ読込に失敗しました: {message}", exit_code=4) from exc
    except OSError as exc:
        raise ZipFlowError(f"出力書込に失敗しました: {exc}", exit_code=7) from exc

    if "raster_bbox" in config.output_kinds:
        for region in regions:
            if len(bbox_frames[region.region_key]) != slot_count:
                count = len(bbox_frames[region.region_key])
                raise ZipFlowError(
                    f"領域 {region.region_key} の raster_bbox 点数が想定と不一致です: "
                    f"expected={slot_count} actual={count}",
                    exit_code=5,
                )
            write_rain_dat_blocks(
                path=raster_bbox_dir / region.region_key / "rain.dat",
                frames=bbox_frames[region.region_key],
                elapsed_seconds=elapsed_seconds,
            )

    csv_paths: list[Path] = []
    cell_csv_paths: list[Path] = []
    csv_readme_path: Path | None = None
    if enable_timeseries_csv:
        for region in regions:
            rows = weighted_rows[region.region_key]
            if len(rows) != slot_count:
                raise ZipFlowError(
                    f"領域 {region.region_key} のCSV系列点数が想定と不一致です: "
                    f"expected={slot_count} actual={len(rows)}",
                    exit_code=5,
                )
            out_csv = csv_dir / region.region_key / f"{region.region_key}_{config.base_date:%Y%m%d}_timeseries.csv"
            out_csv.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(rows).to_csv(out_csv, index=False, encoding="utf-8-sig")
            csv_paths.append(out_csv)
            out_cell_csv = csv_dir / region.region_key / f"{region.region_key}_{config.base_date:%Y%m%d}_cells.csv"
            pd.DataFrame(cell_catalog_rows[region.region_key]).to_csv(out_cell_csv, index=False, encoding="utf-8-sig")
            cell_csv_paths.append(out_cell_csv)
        csv_readme_path = _write_timeseries_csv_readme(
            csv_dir=csv_dir,
            base_date=config.base_date,
            region_keys=[r.region_key for r in regions],
            window_start=window_start,
            window_end=window_end,
            slot_count=slot_count,
        )

    plot_paths: list[Path] = []
    plot_ref_png_paths: list[Path] = []
    plot_frames_by_region: dict[str, dict[str, list[object]]] = {}
    axis_tops_by_region: dict[str, dict[tuple[str, str], tuple[float, float]]] = {}
    if enable_metric_calc:
        for region in regions:
            sum_series = weighted_series[region.region_key]
            mean_series = weighted_mean_series[region.region_key]
            if len(sum_series) != slot_count:
                raise ZipFlowError(
                    f"領域 {region.region_key} の系列点数が想定と不一致です: "
                    f"expected={slot_count} actual={len(sum_series)}",
                    exit_code=5,
                )
            if len(mean_series) != slot_count:
                raise ZipFlowError(
                    f"領域 {region.region_key} の平均系列点数が想定と不一致です: "
                    f"expected={slot_count} actual={len(mean_series)}",
                    exit_code=5,
                )
            frame = build_metric_frame(observed_at=observed_at, weighted_sum=sum_series)
            frame_mean = build_metric_frame(observed_at=observed_at, weighted_sum=mean_series)
            if collect_metric_frames:
                plot_frames_by_region[region.region_key] = {
                    "observed_at_jst": [
                        stamp.strftime("%Y-%m-%d %H:%M:%S")
                        for stamp in frame["observed_at"].to_list()
                        if isinstance(stamp, datetime)
                    ],
                    "weighted_sum_mm": [float(value) for value in frame["rainfall_mm"].to_list()],
                    "weighted_mean_mm": [float(value) for value in frame_mean["rainfall_mm"].to_list()],
                }
            try:
                peaks = find_metric_peaks(frame)
                if "plots_ref" in config.output_kinds:
                    axis_tops = None
                    if shared_axis_tops_by_region is not None:
                        axis_tops = shared_axis_tops_by_region.get(region.region_key)
                    if axis_tops is None:
                        axis_tops = _build_reference_axis_tops_for_run(
                            frame_sum=frame,
                            frame_mean=frame_mean,
                            base_date=reference_base_date,
                            graph_spans=config.graph_spans,
                            ref_graph_kinds=config.ref_graph_kinds,
                            left_top_default=(style_profile.left_axis_top if style_profile is not None else 60.0),
                            right_top_default=(style_profile.right_axis_top if style_profile is not None else 300.0),
                        )
                    axis_tops_by_region[region.region_key] = axis_tops
                    for span, kind in axis_tops:
                        left_top, right_top = axis_tops[(span, kind)]
                        logger.info(
                            "共通軸上限: region=%s span=%s kind=%s left_top=%.3f right_top=%.3f",
                            region.region_key,
                            span,
                            kind,
                            left_top,
                            right_top,
                        )

                if collect_axis_tops_only:
                    continue

                if "plots" in config.output_kinds:
                    plot_paths.extend(
                        render_region_plots(
                            frame=frame,
                            peaks=peaks,
                            region_key=region.region_key,
                            region_label=region.region_name,
                            output_dir=plot_dir,
                            on_conflict=config.on_conflict,
                        )
                    )
                if "plots_ref" in config.output_kinds:
                    axis_tops = axis_tops_by_region.get(region.region_key)
                    generated_ref = render_region_plots_reference(
                        frame_sum=frame,
                        frame_mean=frame_mean,
                        region_key=region.region_key,
                        region_label=region.region_name,
                        output_dir=plot_ref_dir,
                        base_date=reference_base_date,
                        graph_spans=config.graph_spans,
                        ref_graph_kinds=config.ref_graph_kinds,
                        export_svg=config.export_svg,
                        on_conflict=config.on_conflict,
                        style=style_profile,
                        axis_tops=axis_tops or {},
                    )
                    plot_paths.extend(generated_ref)
                    plot_ref_png_paths.extend([path for path in generated_ref if path.suffix.lower() == ".png"])
            except FileExistsError as exc:
                raise ZipFlowError(
                    f"既存ファイルと衝突したため中断しました: {exc} "
                    "(on_conflict=cancel なら期待動作です)",
                    exit_code=7,
                ) from exc
            except OSError as exc:
                raise ZipFlowError(f"グラフ出力に失敗しました: {exc}", exit_code=7) from exc

    if not config.output_kinds and collect_metric_frames:
        logger.info(
            "集計完了（中間データ生成）: outputs=%s regions=%s plot=%s",
            config.output_kinds,
            [r.region_key for r in regions],
            len(plot_paths),
        )
    else:
        logger.info(
            "出力完了: outputs=%s regions=%s plot=%s",
            config.output_kinds,
            [r.region_key for r in regions],
            len(plot_paths),
        )
    return {
        "base_dir": str(raster_dir.parent),
        "raster_dir": str(raster_dir) if "raster" in config.output_kinds else None,
        "raster_bbox_dir": str(raster_bbox_dir) if "raster_bbox" in config.output_kinds else None,
        "plot_dir": str(plot_dir) if "plots" in config.output_kinds else None,
        "plot_ref_dir": str(plot_ref_dir) if "plots_ref" in config.output_kinds else None,
        "analysis_csv_dir": str(csv_dir) if "timeseries_csv" in config.output_kinds else None,
        "timeseries_csv_dir": str(csv_dir) if "timeseries_csv" in config.output_kinds else None,
        "log_path": str(log_path) if config.enable_log else None,
        "zip_count": len(selected),
        "plot_count": len(plot_paths),
        "csv_count": len(csv_paths),
        "cell_csv_count": len(cell_csv_paths),
        "csv_readme_path": str(csv_readme_path) if csv_readme_path else None,
        "axis_tops_by_region": axis_tops_by_region if "plots_ref" in config.output_kinds else {},
        "plot_frames_by_region": plot_frames_by_region if collect_metric_frames else {},
        "plot_ref_png_paths": [str(path) for path in plot_ref_png_paths],
    }
