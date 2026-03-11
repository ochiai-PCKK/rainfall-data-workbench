from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from ..db import initialize_schema, open_db, replace_cell_timeseries, replace_polygon_cell_map, upsert_dataset, upsert_grid, upsert_polygons
from ..ingest import build_grid_definition, iter_cell_rows, load_uc_input_bundle, parse_rain_dat, resolve_observation_times
from ..models import DatasetRecord, GridDefinition
from ..spatial import build_polygon_cell_map, load_polygons

LOGGER = logging.getLogger(__name__)


def _grid_matches(left: pd.Series, right: pd.Series, *, tol: float = 1e-6) -> bool:
    """格子定義が同一とみなせるかを許容誤差付きで判定する。"""
    return (
        str(left["grid_crs"]) == str(right["grid_crs"])
        and abs(float(left["origin_x"]) - float(right["origin_x"])) <= tol
        and abs(float(left["origin_y"]) - float(right["origin_y"])) <= tol
        and abs(float(left["cell_width"]) - float(right["cell_width"])) <= tol
        and abs(float(left["cell_height"]) - float(right["cell_height"])) <= tol
        and int(left["rows"]) == int(right["rows"])
        and int(left["cols"]) == int(right["cols"])
    )


def _build_timeseries_frame(
    observed_times: list[datetime],
    matrices: list[list[list[float]]],
    grid: GridDefinition,
) -> pd.DataFrame:
    """取り込み直後の時系列レコードを DataFrame 化する。"""
    rows = list(iter_cell_rows(observed_times, matrices, grid))
    return pd.DataFrame(
        rows,
        columns=["observed_at", "row", "col", "x_center", "y_center", "rainfall_mm", "quality"],
    )


def _same_nan_aware(left: pd.Series, right: pd.Series) -> pd.Series:
    """NaN 同士を同値とみなして要素比較する。"""
    return (left == right) | (left.isna() & right.isna())


def _check_duplicate_or_conflict(
    conn,
    *,
    dataset_id: str,
    grid: GridDefinition,
    new_frame: pd.DataFrame,
) -> str | None:
    """同一格子の既存データと比較し、重複スキップまたは不整合を判定する。"""
    dataset_exists = bool(
        conn.execute("SELECT 1 FROM datasets WHERE dataset_id = ?", (dataset_id,)).fetchone()
    )
    grids = pd.read_sql_query(
        """
        SELECT dataset_id, grid_crs, origin_x, origin_y, cell_width, cell_height, rows, cols
        FROM grids
        WHERE dataset_id <> ?
        """,
        conn,
        params=(dataset_id,),
    )
    if grids.empty:
        return None

    anchor = pd.Series(
        {
            "grid_crs": grid.grid_crs,
            "origin_x": grid.origin_x,
            "origin_y": grid.origin_y,
            "cell_width": grid.cell_width,
            "cell_height": grid.cell_height,
            "rows": grid.rows,
            "cols": grid.cols,
        }
    )
    candidate_ids = [row["dataset_id"] for _, row in grids.iterrows() if _grid_matches(row, anchor)]
    if not candidate_ids:
        return None

    time_start = str(new_frame["observed_at"].min())
    time_end = str(new_frame["observed_at"].max())
    placeholders = ",".join("?" for _ in candidate_ids)
    existing = pd.read_sql_query(
        f"""
        SELECT dataset_id, observed_at, row, col, rainfall_mm
        FROM cell_timeseries
        WHERE dataset_id IN ({placeholders}) AND observed_at BETWEEN ? AND ?
        """,
        conn,
        params=(*candidate_ids, time_start, time_end),
    )
    if existing.empty:
        return None

    new_cmp = new_frame[["observed_at", "row", "col", "rainfall_mm"]].copy()
    new_cmp["observed_at"] = new_cmp["observed_at"].astype(str)

    for candidate_id in candidate_ids:
        existing_one = existing.loc[existing["dataset_id"] == candidate_id, ["observed_at", "row", "col", "rainfall_mm"]].copy()
        if existing_one.empty:
            continue

        merged = new_cmp.merge(
            existing_one,
            on=["observed_at", "row", "col"],
            how="inner",
            suffixes=("_new", "_existing"),
        )
        if merged.empty:
            continue

        equal_mask = _same_nan_aware(merged["rainfall_mm_new"], merged["rainfall_mm_existing"])
        if not bool(equal_mask.all()):
            mismatched = merged.loc[~equal_mask].iloc[0]
            raise ValueError(
                "重複時刻に不整合があります: "
                f"dataset_id={candidate_id} observed_at={mismatched['observed_at']} "
                f"row={int(mismatched['row'])} col={int(mismatched['col'])} "
                f"新規値={mismatched['rainfall_mm_new']} 既存値={mismatched['rainfall_mm_existing']}"
            )

        same_shape = len(existing_one) == len(new_cmp)
        same_keys = len(merged) == len(new_cmp)
        if same_shape and same_keys and not dataset_exists:
            LOGGER.info("取り込みをスキップします。dataset_id=%s は既存 dataset_id=%s と完全一致です", dataset_id, candidate_id)
            return candidate_id

    return None


def ingest_uc_rainfall(
    *,
    db_path: str | Path,
    input_path: str | Path,
    polygon_dir: str | Path,
    dataset_id: str | None = None,
    grid_crs: str = "EPSG:4326",
) -> None:
    """UC-tools 入力を解析して DB へ登録し、流域-セル対応まで構築する。"""
    with load_uc_input_bundle(input_path, dataset_id=dataset_id) as bundle:
        elapsed_seconds, matrices, rows, cols = parse_rain_dat(bundle.rain_dat_path)
        observed_times = resolve_observation_times(bundle.raster_paths, elapsed_seconds)
        grid = build_grid_definition(
            bundle.dataset_id,
            rows,
            cols,
            bundle.mail_text_path,
            bundle.raster_paths,
            grid_crs=grid_crs,
        )
        polygon_records, polygon_frames = load_polygons(polygon_dir)
        new_frame = _build_timeseries_frame(observed_times, matrices, grid)

        dataset = DatasetRecord(
            dataset_id=bundle.dataset_id,
            source_type="uc_tools",
            source_dir=str(bundle.source_path),
            time_start=min(observed_times) if observed_times else None,
            time_end=max(observed_times) if observed_times else None,
            crs_raw=grid.grid_crs,
            created_at=datetime.now(),
        )

        with open_db(db_path) as conn:
            initialize_schema(conn)
            duplicate_of = _check_duplicate_or_conflict(
                conn,
                dataset_id=bundle.dataset_id,
                grid=grid,
                new_frame=new_frame,
            )
            if duplicate_of is not None:
                return
            upsert_dataset(conn, dataset)
            upsert_grid(conn, grid)
            replace_cell_timeseries(conn, bundle.dataset_id, new_frame.itertuples(index=False, name=None))
            upsert_polygons(conn, polygon_records)
            replace_polygon_cell_map(conn, bundle.dataset_id, build_polygon_cell_map(grid, polygon_records, polygon_frames))

        LOGGER.info(
            "取り込み完了: dataset_id=%s source=%s 観測数=%s 格子=%sx%s",
            bundle.dataset_id,
            bundle.source_path,
            len(observed_times),
            rows,
            cols,
        )
