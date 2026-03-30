from __future__ import annotations

import json
from pathlib import Path

from ..runtime_paths import resolve_path

GUI_STATE_PATH = resolve_path("config", "uc_rainfall_zipflow", "gui_state.json")


def load_state() -> dict[str, object]:
    if not GUI_STATE_PATH.exists():
        return {}
    try:
        raw = json.loads(GUI_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def save_state(state: dict[str, object]) -> None:
    GUI_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    GUI_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
