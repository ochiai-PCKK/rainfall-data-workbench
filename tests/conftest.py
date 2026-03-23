from __future__ import annotations

import uuid
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROOT_TEXT = str(PROJECT_ROOT)
if ROOT_TEXT not in sys.path:
    sys.path.insert(0, ROOT_TEXT)

SRC_DIR = PROJECT_ROOT / "src"
SRC_TEXT = str(SRC_DIR)
if SRC_TEXT not in sys.path:
    sys.path.insert(0, SRC_TEXT)


def pytest_configure(config) -> None:
    root = Path(__file__).resolve().parents[1] / ".pytest-tmp"
    root.mkdir(parents=True, exist_ok=True)
    run_dir = root / f"run-{uuid.uuid4().hex}"
    run_dir.mkdir(parents=True, exist_ok=True)
    config.option.basetemp = str(run_dir)
