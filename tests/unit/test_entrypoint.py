from __future__ import annotations

import sys
from pathlib import Path

import run_uc_rainfall_gui


def test_resolve_base_dir_uses_script_directory() -> None:
    expected = Path(run_uc_rainfall_gui.__file__).resolve().parent
    assert run_uc_rainfall_gui._resolve_base_dir() == expected


def test_ensure_src_on_syspath_adds_src_once(tmp_path: Path) -> None:
    base_dir = tmp_path
    src_dir = base_dir / "src"
    src_dir.mkdir()
    original = list(sys.path)
    try:
        sys.path[:] = [entry for entry in sys.path if entry != str(src_dir)]
        run_uc_rainfall_gui._ensure_src_on_syspath(base_dir)
        assert sys.path[0] == str(src_dir)
        run_uc_rainfall_gui._ensure_src_on_syspath(base_dir)
        assert sys.path.count(str(src_dir)) == 1
    finally:
        sys.path[:] = original
