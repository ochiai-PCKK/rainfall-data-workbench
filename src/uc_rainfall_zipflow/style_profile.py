from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


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
    axis_label_fontsize: float = 10.0
    tick_fontsize: float = 8.0
    line_width: float = 2.7
    bar_width_hours: float = 0.96
    bar_edge_linewidth: float = 0.4
    table_height_ratio: float = 1.8
    table_row_top_y: float = 1.5
    table_row_bottom_y: float = 0.38
    table_vertical_linewidth: float = 0.8
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
    project_root = Path(__file__).resolve().parents[2]
    return project_root / "config" / "uc_rainfall_zipflow" / "styles" / "default.json"


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
