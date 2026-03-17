from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from shapely.geometry.base import BaseGeometry


@dataclass(frozen=True)
class RunConfig:
    base_date: date
    input_zipdir: Path
    output_root: Path
    polygon_dir: Path
    enable_log: bool
    region_keys: tuple[str, ...]
    output_kinds: tuple[str, ...]


@dataclass(frozen=True)
class TimeSlot:
    index: int
    observed_at_jst: datetime
    relative_seconds: int


@dataclass(frozen=True)
class ZipWindow:
    path: Path
    start_at: datetime
    end_at: datetime


@dataclass(frozen=True)
class RegionSpec:
    region_key: str
    region_name: str
    geometry_6674: BaseGeometry
    bbox_6674: tuple[float, float, float, float]
