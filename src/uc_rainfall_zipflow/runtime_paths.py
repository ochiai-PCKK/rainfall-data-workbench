from __future__ import annotations

import os
from pathlib import Path

_BASE_DIR_ENV = "UC_RAINFALL_BASE_DIR"


def get_base_dir() -> Path:
    raw = os.environ.get(_BASE_DIR_ENV, "").strip()
    if raw:
        return Path(raw).resolve()
    return Path.cwd().resolve()


def set_base_dir(path: Path) -> Path:
    resolved = path.resolve()
    os.environ[_BASE_DIR_ENV] = str(resolved)
    return resolved


def resolve_path(*parts: str) -> Path:
    return get_base_dir().joinpath(*parts)

