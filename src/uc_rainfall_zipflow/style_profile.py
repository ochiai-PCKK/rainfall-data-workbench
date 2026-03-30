from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .runtime_paths import resolve_path


def _coerce_x_tick_hours_list(value: Any) -> list[int]:
    values: list[int] = []
    if isinstance(value, (list, tuple)):
        source = value
    elif isinstance(value, str):
        source = [part.strip() for part in value.split(",") if part.strip()]
    else:
        source = []
    for item in source:
        try:
            hour = int(item)
        except (TypeError, ValueError):
            continue
        if hour == 0:
            # 旧設定（0時指定）を 24 時に読み替える。
            hour = 24
        if 1 <= hour <= 24:
            values.append(hour)
    unique_sorted = sorted(set(values))
    return unique_sorted if unique_sorted else [6, 12, 18]


@dataclass(frozen=True)
class GraphStyleProfile:
    fig_width: float = 10.0
    fig_height: float = 5.0
    dpi: int = 120
    left: float = 0.08
    right: float = 0.92
    top: float = 0.92
    bottom: float = 0.08
    hspace: float = 0.0
    title_fontsize: float = 10.0
    title_pad: float = 8.0
    axis_label_fontsize: float = 10.0
    y1_label_pad: float = 6.0
    y2_label_pad: float = 16.0
    y_tick_pad: float = 4.0
    tick_fontsize: float = 8.0
    x_tick_hours_list: list[int] = field(default_factory=lambda: [6, 12, 18])
    x_date_label_format: str = "%Y.%m.%d"
    x_margin_hours_left: float = 0.5
    x_margin_hours_right: float = 0.5
    left_axis_top: float = 60.0
    right_axis_top: float = 300.0
    left_major_tick_count: int = 7
    right_major_tick_count: int = 7
    left_major_tick_step: float = 10.0
    right_major_tick_step: float = 50.0
    line_width: float = 2.7
    bar_width_hours: float = 0.96
    bar_edge_linewidth: float = 0.4
    table_height_ratio: float = 1.8
    table_row_top_y: float = 1.5
    table_row_bottom_y: float = 0.38
    table_vertical_linewidth: float = 0.8
    day_boundary_offset_hours: float = 0.0
    grid_y_visible: bool = True
    grid_y_linewidth: float = 0.6
    grid_y_color: str = "gray"
    grid_y_alpha: float = 0.5
    grid_x_visible: bool = True
    grid_x_linewidth: float = 0.6
    grid_x_color: str = "gray"
    grid_x_alpha: float = 0.5


def default_style_profile() -> GraphStyleProfile:
    return GraphStyleProfile()


def default_style_profile_path() -> Path:
    return resolve_path("config", "uc_rainfall_zipflow", "styles", "default.json")


def _coerce_profile(raw: dict[str, Any]) -> GraphStyleProfile:
    # 旧キー互換
    if "grid_visible" in raw:
        raw.setdefault("grid_y_visible", raw["grid_visible"])
        raw.setdefault("grid_x_visible", raw["grid_visible"])
    if "grid_linewidth" in raw:
        raw.setdefault("grid_y_linewidth", raw["grid_linewidth"])
        raw.setdefault("grid_x_linewidth", raw["grid_linewidth"])
    if "grid_color" in raw:
        raw.setdefault("grid_y_color", raw["grid_color"])
        raw.setdefault("grid_x_color", raw["grid_color"])
    if "grid_alpha" in raw:
        raw.setdefault("grid_y_alpha", raw["grid_alpha"])
        raw.setdefault("grid_x_alpha", raw["grid_alpha"])
    # 旧キー互換（連動 -> 左右別）
    if "y_label_pad" in raw:
        linked = float(raw["y_label_pad"])
        raw.setdefault("y1_label_pad", linked)
        raw.setdefault("y2_label_pad", linked)

    defaults = asdict(default_style_profile())
    merged: dict[str, Any] = {}
    for key, default in defaults.items():
        value = raw.get(key, default)
        if isinstance(default, bool):
            merged[key] = bool(value)
        elif isinstance(default, int):
            merged[key] = int(value)
        elif isinstance(default, float):
            merged[key] = float(value)
        elif key == "x_tick_hours_list":
            merged[key] = _coerce_x_tick_hours_list(value)
        elif key == "x_date_label_format":
            merged[key] = str(value)
        else:
            merged[key] = value
    return GraphStyleProfile(**merged)


def load_style_profile(path: Path | None) -> GraphStyleProfile:
    if path is None:
        return default_style_profile()
    if not path.exists():
        raise FileNotFoundError(f"スタイルプロファイルが見つかりません: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("スタイルプロファイルのJSON形式が不正です。")
    return _coerce_profile(data)


def save_style_profile(path: Path, profile: GraphStyleProfile) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(profile), ensure_ascii=False, indent=2), encoding="utf-8")
    return path
