from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import logging
import re

import pandas as pd

from ..db import open_db
from ..graph import add_metric_columns, find_metric_events, render_metric_chart

LOGGER = logging.getLogger(__name__)


def _safe_token(value: str) -> str:
    """ファイル名に使いづらい文字を安全な文字へ置き換える。"""
    return re.sub(r"[^\w\-]+", "_", value).strip("_")


def _grid_matches(left: pd.Series, right: pd.Series, *, tol: float = 1e-6) -> bool:
    """格子定義が同一かどうかを許容誤差付きで判定する。"""
    return (
        str(left["grid_crs"]) == str(right["grid_crs"])
        and abs(float(left["origin_x"]) - float(right["origin_x"])) <= tol
        and abs(float(left["origin_y"]) - float(right["origin_y"])) <= tol
        and abs(float(left["cell_width"]) - float(right["cell_width"])) <= tol
        and abs(float(left["cell_height"]) - float(right["cell_height"])) <= tol
        and int(left["rows"]) == int(right["rows"])
        and int(left["cols"]) == int(right["cols"])
    )


def _load_compatible_dataset_ids(
    frame: pd.DataFrame,
    *,
    anchor_dataset_id: str,
) -> list[str]:
    """起点データセットと同じ格子定義を持つ `dataset_id` 一覧を返す。"""
    anchor = frame.loc[frame["dataset_id"] == anchor_dataset_id]
    if anchor.empty:
        raise ValueError(f"格子定義が見つかりません: dataset_id={anchor_dataset_id}")
    anchor_row = anchor.iloc[0]

    compatible = [
        row["dataset_id"]
        for _, row in frame.iterrows()
        if _grid_matches(row, anchor_row)
    ]

    compatible_sorted = [anchor_dataset_id] + sorted(dataset_id for dataset_id in compatible if dataset_id != anchor_dataset_id)
    return compatible_sorted


def _fetch_compatible_frames(
    *,
    conn,
    dataset_id: str,
    polygon_name: str,
    row: int,
    col: int,
    calc_start: datetime,
    view_end: datetime,
) -> tuple[pd.DataFrame, list[str]]:
    """同一格子定義を持つデータセット群から、指定セルの時系列を取得する。"""
    membership = conn.execute(
        """
        SELECT 1
        FROM polygon_cell_map pcm
        JOIN polygons p ON p.polygon_id = pcm.polygon_id
        WHERE pcm.dataset_id = ? AND p.polygon_name = ? AND pcm.row = ? AND pcm.col = ?
        """,
        (dataset_id, polygon_name, row, col),
    ).fetchone()
    if membership is None:
        raise ValueError(f"row={row}, col={col} は流域 {polygon_name} の候補セルではありません")

    grids = pd.read_sql_query(
        """
        SELECT dataset_id, grid_crs, origin_x, origin_y, cell_width, cell_height, rows, cols
        FROM grids
        """,
        conn,
    )
    compatible_dataset_ids = _load_compatible_dataset_ids(grids, anchor_dataset_id=dataset_id)

    placeholders = ",".join("?" for _ in compatible_dataset_ids)
    frame = pd.read_sql_query(
        f"""
        SELECT dataset_id, observed_at, rainfall_mm, quality
        FROM cell_timeseries
        WHERE dataset_id IN ({placeholders}) AND row = ? AND col = ? AND observed_at BETWEEN ? AND ?
        ORDER BY observed_at
        """,
        conn,
        params=(
            *compatible_dataset_ids,
            row,
            col,
            calc_start.isoformat(timespec="seconds"),
            view_end.isoformat(timespec="seconds"),
        ),
    )
    return frame, compatible_dataset_ids


def _deduplicate_rows(
    frame: pd.DataFrame,
    *,
    anchor_dataset_id: str,
    subset_cols: list[str],
) -> pd.DataFrame:
    """同一キーの重複行を起点データセット優先で1件に絞る。"""
    if frame.empty:
        return frame

    dataset_priority = {anchor_dataset_id: 0}
    next_priority = 1
    for dataset_id in frame["dataset_id"].drop_duplicates().tolist():
        if dataset_id not in dataset_priority:
            dataset_priority[dataset_id] = next_priority
            next_priority += 1

    ranked = frame.copy()
    ranked["priority"] = ranked["dataset_id"].map(dataset_priority)
    ranked = ranked.sort_values([*subset_cols, "priority", "dataset_id"]).reset_index(drop=True)

    duplicated = ranked[ranked.duplicated(subset=subset_cols, keep=False)]
    if not duplicated.empty:
        grouped = duplicated.groupby(subset_cols)["dataset_id"].apply(list)
        LOGGER.info("重複グループ数=%s 優先データセット=%s", len(grouped), anchor_dataset_id)
        max_examples = 5
        for idx, (key, dataset_ids) in enumerate(grouped.items()):
            if idx >= max_examples:
                LOGGER.info("重複ログを省略しました。残り=%s", len(grouped) - max_examples)
                break
            LOGGER.info(
                "重複キー=%s データセット=%s 採用=%s",
                key,
                dataset_ids,
                dataset_ids[0],
            )

    deduped = ranked.drop_duplicates(subset=subset_cols, keep="first").drop(columns=["priority"])
    return deduped


def _build_continuous_hourly_frame(
    frame: pd.DataFrame,
    *,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    group_cols: list[str] | None = None,
) -> pd.DataFrame:
    """欠測時刻を補って連続した1時間時系列へ整形する。"""
    if frame.empty:
        return frame

    if group_cols:
        result_frames: list[pd.DataFrame] = []
        for keys, group in frame.groupby(group_cols, sort=False):
            indexed = group.set_index("observed_at").sort_index()
            range_start = pd.Timestamp(start_at).floor("h") if start_at is not None else indexed.index.min().floor("h")
            local_end = pd.Timestamp(end_at).floor("h") if end_at is not None else indexed.index.max().floor("h")
            full_index = pd.date_range(range_start, local_end, freq="h")
            aligned = indexed.reindex(full_index)
            aligned.index.name = "observed_at"
            aligned["rainfall_mm"] = pd.to_numeric(aligned["rainfall_mm"], errors="coerce")
            aligned["quality"] = aligned.get("quality")
            aligned.loc[aligned["quality"].isna() & aligned["rainfall_mm"].isna(), "quality"] = "missing"
            aligned.loc[aligned["quality"].isna() & aligned["rainfall_mm"].notna(), "quality"] = "normal"
            if not isinstance(keys, tuple):
                keys = (keys,)
            for column, value in zip(group_cols, keys):
                aligned[column] = value
            result_frames.append(aligned.reset_index())
        return pd.concat(result_frames, ignore_index=True)

    indexed = frame.set_index("observed_at").sort_index()
    range_start = pd.Timestamp(start_at).floor("h") if start_at is not None else indexed.index.min().floor("h")
    range_end = pd.Timestamp(end_at).floor("h") if end_at is not None else indexed.index.max().floor("h")
    full_index = pd.date_range(range_start, range_end, freq="h")
    aligned = indexed.reindex(full_index)
    aligned.index.name = "observed_at"
    aligned["rainfall_mm"] = pd.to_numeric(aligned["rainfall_mm"], errors="coerce")
    aligned["quality"] = aligned.get("quality")
    aligned.loc[aligned["quality"].isna() & aligned["rainfall_mm"].isna(), "quality"] = "missing"
    aligned.loc[aligned["quality"].isna() & aligned["rainfall_mm"].notna(), "quality"] = "normal"
    return aligned.reset_index()


def _load_candidate_cells(conn, *, dataset_id: str, polygon_name: str) -> pd.DataFrame:
    """指定流域に属する候補セル一覧を DB から取得する。"""
    frame = pd.read_sql_query(
        """
        SELECT pcm.row, pcm.col
        FROM polygon_cell_map pcm
        JOIN polygons p ON p.polygon_id = pcm.polygon_id
        WHERE pcm.dataset_id = ? AND p.polygon_name = ?
        ORDER BY pcm.row, pcm.col
        """,
        conn,
        params=(dataset_id, polygon_name),
    )
    if frame.empty:
        raise ValueError(f"流域 {polygon_name} の候補セルが見つかりません")
    return frame


def _fetch_polygon_frames(
    *,
    conn,
    compatible_dataset_ids: list[str],
    anchor_dataset_id: str,
    polygon_name: str,
    calc_start: datetime,
    view_end: datetime,
) -> pd.DataFrame:
    """指定流域に属する全候補セルの時系列を取得する。"""
    placeholders = ",".join("?" for _ in compatible_dataset_ids)
    return pd.read_sql_query(
        f"""
        SELECT c.dataset_id, c.observed_at, c.row, c.col, c.rainfall_mm, c.quality
        FROM cell_timeseries c
        JOIN polygon_cell_map pcm
          ON pcm.dataset_id = ? AND pcm.row = c.row AND pcm.col = c.col
        JOIN polygons p
          ON p.polygon_id = pcm.polygon_id
        WHERE c.dataset_id IN ({placeholders})
          AND p.polygon_name = ?
          AND c.observed_at BETWEEN ? AND ?
        ORDER BY c.observed_at, c.row, c.col
        """,
        conn,
        params=(
            anchor_dataset_id,
            *compatible_dataset_ids,
            polygon_name,
            calc_start.isoformat(timespec="seconds"),
            view_end.isoformat(timespec="seconds"),
        ),
    )


def _aggregate_polygon_frame(frame: pd.DataFrame, *, mode: str) -> pd.DataFrame:
    """流域内セル時系列を合計または平均へ集約する。"""
    grouped = frame.groupby("observed_at", sort=True)
    if mode == "polygon_sum":
        rainfall = grouped["rainfall_mm"].agg(lambda s: s.sum(min_count=1))
    elif mode == "polygon_mean":
        rainfall = grouped["rainfall_mm"].mean()
    else:
        raise ValueError(f"未対応の集計モードです: {mode}")

    quality = grouped["rainfall_mm"].agg(lambda s: "missing" if s.notna().sum() == 0 else "normal")
    result = pd.DataFrame(
        {
            "observed_at": rainfall.index,
            "rainfall_mm": rainfall.to_numpy(),
            "quality": quality.to_numpy(),
        }
    )
    return result.reset_index(drop=True)


def generate_metric_event_charts(
    *,
    db_path: str | Path,
    dataset_id: str,
    polygon_name: str,
    row: int | None,
    col: int | None,
    series_mode: str,
    view_start: datetime,
    view_end: datetime,
    out_dir: str | Path,
) -> list[Path]:
    """指定セルまたは流域集計系列から最大イベントグラフ群を出力する。"""
    calc_start = view_start - timedelta(hours=48)
    with open_db(db_path) as conn:
        grids = pd.read_sql_query(
            """
            SELECT dataset_id, grid_crs, origin_x, origin_y, cell_width, cell_height, rows, cols
            FROM grids
            """,
            conn,
        )
        compatible_dataset_ids = _load_compatible_dataset_ids(grids, anchor_dataset_id=dataset_id)
        if series_mode == "cell":
            if row is None or col is None:
                raise ValueError("--series-mode=cell のときは --row と --col が必須です")
            frame, compatible_dataset_ids = _fetch_compatible_frames(
                conn=conn,
                dataset_id=dataset_id,
                polygon_name=polygon_name,
                row=row,
                col=col,
                calc_start=calc_start,
                view_end=view_end,
            )
        else:
            candidate_cells = _load_candidate_cells(conn, dataset_id=dataset_id, polygon_name=polygon_name)
            LOGGER.info("流域集計を実行します: polygon=%s 候補セル数=%s mode=%s", polygon_name, len(candidate_cells), series_mode)
            frame = _fetch_polygon_frames(
                conn=conn,
                compatible_dataset_ids=compatible_dataset_ids,
                anchor_dataset_id=dataset_id,
                polygon_name=polygon_name,
                calc_start=calc_start,
                view_end=view_end,
            )

    if frame.empty:
        raise ValueError("指定条件に該当する時系列データが見つかりません")

    LOGGER.info("使用データセット=%s", compatible_dataset_ids)
    frame["observed_at"] = pd.to_datetime(frame["observed_at"], errors="coerce")
    frame["rainfall_mm"] = pd.to_numeric(frame["rainfall_mm"], errors="coerce")
    frame = frame.dropna(subset=["observed_at"]).sort_values("observed_at").reset_index(drop=True)
    if series_mode == "cell":
        frame = _deduplicate_rows(frame, anchor_dataset_id=dataset_id, subset_cols=["observed_at"])
        frame = _build_continuous_hourly_frame(frame, start_at=calc_start, end_at=view_end)
    else:
        frame = _deduplicate_rows(frame, anchor_dataset_id=dataset_id, subset_cols=["observed_at", "row", "col"])
        frame = _build_continuous_hourly_frame(
            frame,
            start_at=calc_start,
            end_at=view_end,
            group_cols=["row", "col"],
        )
        frame = _aggregate_polygon_frame(frame, mode=series_mode)
    frame = add_metric_columns(frame)

    output_paths: list[Path] = []
    for event in find_metric_events(frame, view_start=view_start, view_end=view_end):
        event_stamp = event.occurred_at.strftime("%Y%m%dT%H%M%SJST")
        if series_mode == "cell":
            filename = (
                f"{_safe_token(dataset_id)}_{_safe_token(polygon_name)}_"
                f"r{row}_c{col}_{event.metric}_{event_stamp}.png"
            )
            title = f"{polygon_name} row={row} col={col} {event.metric}最大雨量"
        else:
            suffix = "全セル合計" if series_mode == "polygon_sum" else "全セル平均"
            filename = (
                f"{_safe_token(dataset_id)}_{_safe_token(polygon_name)}_"
                f"{_safe_token(suffix)}_{event.metric}_{event_stamp}.png"
            )
            title = f"{polygon_name} {suffix} {event.metric}最大雨量"
        output_paths.append(
            render_metric_chart(
                frame,
                metric=event.metric,
                event_time=event.occurred_at,
                output_path=Path(out_dir) / filename,
                title=title,
            )
        )
    return output_paths
