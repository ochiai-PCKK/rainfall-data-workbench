from __future__ import annotations

import re
import zipfile
from datetime import datetime, time
from pathlib import Path

from .models import ZipWindow

_NAME_RANGE_RE = re.compile(r"(\d{8})_(\d{8})")
_JST_RE = re.compile(r"_JST_(\d{8})_(\d{6})")


def _parse_name_range(path: Path) -> tuple[datetime, datetime] | None:
    match = _NAME_RANGE_RE.search(path.stem)
    if match is None:
        return None
    start = datetime.strptime(match.group(1), "%Y%m%d")
    end = datetime.combine(datetime.strptime(match.group(2), "%Y%m%d").date(), time(hour=23))
    return start, end


def _parse_from_zip_members(path: Path) -> tuple[datetime, datetime]:
    times: list[datetime] = []
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            match = _JST_RE.search(name)
            if match is None:
                continue
            times.append(datetime.strptime(f"{match.group(1)}{match.group(2)}", "%Y%m%d%H%M%S"))
    if not times:
        raise ValueError(f"ZIP から期間を解釈できません: {path}")
    return min(times), max(times)


def _resolve_window(path: Path) -> tuple[datetime, datetime]:
    name_range = _parse_name_range(path)
    if name_range is not None:
        return name_range
    return _parse_from_zip_members(path)


def list_zip_windows(*, input_zipdir: Path) -> list[ZipWindow]:
    """入力ディレクトリ内のZIPと期間を列挙する。"""
    if not input_zipdir.exists():
        raise FileNotFoundError(f"入力 ZIP ディレクトリが見つかりません: {input_zipdir}")
    if not input_zipdir.is_dir():
        raise NotADirectoryError(f"入力 ZIP ディレクトリではありません: {input_zipdir}")

    windows: list[ZipWindow] = []
    for path in sorted(input_zipdir.glob("*.zip"), key=lambda p: p.name):
        start_at, end_at = _resolve_window(path)
        windows.append(ZipWindow(path=path, start_at=start_at, end_at=end_at))
    return windows


def select_target_zips(*, input_zipdir: Path, window_start: datetime, window_end: datetime) -> list[ZipWindow]:
    """対象期間と重なる ZIP を選定する。"""
    windows = list_zip_windows(input_zipdir=input_zipdir)
    return select_target_zips_from_windows(windows=windows, window_start=window_start, window_end=window_end)


def select_target_zips_from_windows(
    *,
    windows: list[ZipWindow],
    window_start: datetime,
    window_end: datetime,
) -> list[ZipWindow]:
    """既存の ZIP 期間一覧から、対象期間と重なる ZIP を選定する。"""
    selected: list[ZipWindow] = []
    for item in windows:
        start_at, end_at = item.start_at, item.end_at
        if start_at <= window_end and window_start <= end_at:
            selected.append(item)

    if not selected:
        raise ValueError("対象期間に重なる ZIP が見つかりません。")
    return selected
