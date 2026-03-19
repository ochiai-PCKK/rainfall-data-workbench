from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

import run_uc_rainfall_gui


@pytest.mark.parametrize(
    ("argv", "expected_dev_mode"),
    [
        (["run_uc_rainfall_gui.py"], None),
        (["run_uc_rainfall_gui.py", "true"], True),
        (["run_uc_rainfall_gui.py", "false"], False),
    ],
)
def test_main_bootstrap_calls_runtime_and_gui(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    argv: list[str],
    expected_dev_mode: bool | None,
) -> None:
    base_dir = tmp_path
    src_dir = base_dir / "src"
    src_dir.mkdir()
    captured: dict[str, object] = {}

    monkeypatch.setattr(run_uc_rainfall_gui, "_resolve_base_dir", lambda: base_dir)
    monkeypatch.setattr(run_uc_rainfall_gui.os, "chdir", lambda target: captured.setdefault("chdir", target))
    monkeypatch.setattr(sys, "argv", argv)

    runtime_module = types.ModuleType("uc_rainfall_zipflow.runtime_paths")
    runtime_module.set_base_dir = lambda value: captured.setdefault("base_dir", value)
    gui_module = types.ModuleType("uc_rainfall_zipflow.gui.app")
    gui_module.launch_zipflow_gui = lambda *, dev_mode=None: captured.setdefault("dev_mode", dev_mode)
    monkeypatch.setitem(sys.modules, "uc_rainfall_zipflow.runtime_paths", runtime_module)
    monkeypatch.setitem(sys.modules, "uc_rainfall_zipflow.gui.app", gui_module)

    original = list(sys.path)
    inserted = False
    try:
        sys.path[:] = [entry for entry in sys.path if entry != str(src_dir)]
        run_uc_rainfall_gui.main()
        inserted = str(src_dir) in sys.path
    finally:
        sys.path[:] = original

    assert captured["chdir"] == base_dir
    assert captured["base_dir"] == base_dir
    assert captured["dev_mode"] is expected_dev_mode
    assert inserted
