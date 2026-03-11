from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SETTINGS_PATH = _PROJECT_ROOT / ".uc_rainfall_settings.json"


def get_settings_path() -> Path:
    """設定キャッシュ JSON の保存先を返す。"""
    return _SETTINGS_PATH


def load_settings() -> dict[str, Any]:
    """設定キャッシュを読み込む。未作成時は空辞書を返す。"""
    path = get_settings_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(settings: Mapping[str, Any]) -> Path:
    """設定キャッシュを保存する。"""
    path = get_settings_path()
    serializable: dict[str, Any] = {}
    for key, value in settings.items():
        if isinstance(value, Path):
            serializable[key] = str(value)
        elif isinstance(value, (str, int, float, bool)) or value is None:
            serializable[key] = value
        elif isinstance(value, list):
            serializable[key] = [str(item) if isinstance(item, Path) else item for item in value]
    path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def update_settings(**kwargs: Any) -> Path:
    """既存設定へ差分をマージして保存する。"""
    current = load_settings()
    for key, value in kwargs.items():
        if value is not None:
            current[key] = str(value) if isinstance(value, Path) else value
    return save_settings(current)
