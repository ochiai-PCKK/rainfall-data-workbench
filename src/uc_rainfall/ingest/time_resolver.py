from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

JST_RE = re.compile(r"_JST_(\d{8})_(\d{6})")
UTC_RE = re.compile(r"RJTD_(\d{14})")


def _parse_jst_from_name(path: Path) -> datetime | None:
    """ファイル名中の JST タイムスタンプを抽出する。"""
    match = JST_RE.search(path.name)
    if match is None:
        return None
    return datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S")


def _parse_utc_from_name(path: Path) -> datetime | None:
    """ファイル名中の UTC 相当タイムスタンプを JST へ変換して返す。"""
    match = UTC_RE.search(path.name)
    if match is None:
        return None
    return datetime.strptime(match.group(1), "%Y%m%d%H%M%S") + timedelta(hours=9)


def resolve_observation_times(raster_paths: tuple[Path, ...], elapsed_seconds: list[int]) -> list[datetime]:
    """ラスタ名と経過秒から観測時刻列を決定する。"""
    if raster_paths:
        jst_times = [_parse_jst_from_name(path) for path in raster_paths]
        if all(item is not None for item in jst_times):
            if len(jst_times) != len(elapsed_seconds):
                raise ValueError(
                    f"ラスタの JST 時刻数が rain.dat ブロック数と一致しません: {len(jst_times)} != {len(elapsed_seconds)}"
                )
            return list(jst_times)  # type: ignore[arg-type]

        utc_times = [_parse_utc_from_name(path) for path in raster_paths]
        if all(item is not None for item in utc_times):
            if len(utc_times) != len(elapsed_seconds):
                raise ValueError(
                    f"ラスタの UTC 時刻数が rain.dat ブロック数と一致しません: {len(utc_times)} != {len(elapsed_seconds)}"
                )
            return list(utc_times)  # type: ignore[arg-type]

    if not elapsed_seconds:
        raise ValueError("観測時刻を復元できませんでした。")

    start = datetime(2000, 1, 1, 0, 0, 0)
    return [start + timedelta(seconds=seconds) for seconds in elapsed_seconds]
