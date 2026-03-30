from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path


def parse_date(raw: str, *, field_name: str, date_fmt: str = "%Y-%m-%d") -> date:
    try:
        return datetime.strptime(raw.strip(), date_fmt).date()
    except ValueError as exc:
        raise ValueError(f"{field_name} は YYYY-MM-DD 形式で入力してください。") from exc


def resolve_base_date(start_date: date, end_date: date) -> date:
    day_count = (end_date - start_date).days + 1
    return start_date + timedelta(days=day_count // 2)


def list_available_region_keys(polygon_dir: Path) -> set[str]:
    from ..regions import load_region_specs

    try:
        specs = load_region_specs(polygon_dir)
    except Exception:
        return set()
    return {spec.region_key for spec in specs}


def find_latest_timeseries_csv(*, output_root: Path, region_key: str) -> Path | None:
    if not output_root.exists():
        return None
    pattern = f"*/analysis_csv/{region_key}/{region_key}_*_timeseries.csv"
    candidates = [p for p in output_root.glob(pattern) if p.is_file()]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]
