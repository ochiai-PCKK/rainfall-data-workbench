from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class DatasetRecord:
    dataset_id: str
    source_type: str
    source_dir: str
    time_start: datetime | None
    time_end: datetime | None
    crs_raw: str | None
    created_at: datetime


@dataclass(frozen=True)
class GridDefinition:
    dataset_id: str
    grid_crs: str
    origin_x: float
    origin_y: float
    cell_width: float
    cell_height: float
    rows: int
    cols: int


@dataclass(frozen=True)
class PolygonRecord:
    polygon_id: str
    polygon_name: str
    polygon_group: str | None
    polygon_crs: str
    minx: float
    miny: float
    maxx: float
    maxy: float
    geometry_wkt: str
    file_path: str


@dataclass(frozen=True)
class UcInputBundle:
    dataset_id: str
    source_path: Path
    input_dir: Path
    rain_dat_path: Path
    raster_paths: tuple[Path, ...]
    mail_text_path: Path | None


@dataclass(frozen=True)
class MetricEvent:
    metric: str
    window_hours: int
    occurred_at: datetime
    value: float
    duplicate_times: tuple[datetime, ...]
