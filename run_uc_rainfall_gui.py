from __future__ import annotations

import os
import sys
from pathlib import Path


def _resolve_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _ensure_src_on_syspath(base_dir: Path) -> None:
    src_dir = base_dir / "src"
    if src_dir.is_dir():
        src_text = str(src_dir)
        if src_text not in sys.path:
            sys.path.insert(0, src_text)


def main() -> None:
    base_dir = _resolve_base_dir()
    os.chdir(base_dir)
    _ensure_src_on_syspath(base_dir)

    from uc_rainfall_zipflow.runtime_paths import set_base_dir

    set_base_dir(base_dir)

    from uc_rainfall_zipflow.gui.app import launch_zipflow_gui

    launch_zipflow_gui()


if __name__ == "__main__":
    main()
