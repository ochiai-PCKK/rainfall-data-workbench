from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from uc_rainfall_zipflow.excel_application import resolve_effective_base_date
from uc_rainfall_zipflow.gui.app import (
    ZipFlowGui,
    _load_gui_help_text_from_candidates,
)
from uc_rainfall_zipflow.gui.help_service import DEFAULT_GUI_HELP_TEXT, get_gui_help_text
from uc_rainfall_zipflow.gui.rain_mode_panel import RainModePanel


@dataclass
class DummyVar:
    value: object

    def get(self) -> object:
        return self.value

    def set(self, value: object) -> None:
        self.value = value


class DummyRainPanel:
    def __init__(self, *, target_dates: list[date], window_mode: str, auto_mode: bool) -> None:
        self._target_dates = target_dates
        self._window_mode = window_mode
        self._auto_mode = auto_mode

    def is_auto_mode(self) -> bool:
        return self._auto_mode

    def get_selected_target_dates(self) -> list[date]:
        return list(self._target_dates)

    def get_window_mode(self) -> str:
        return self._window_mode

    def build_window_for_date(self, target_date: date) -> tuple[datetime, datetime, int]:
        start, end = RainModePanel._resolve_window(None, target_date, self._window_mode)
        return start, end, 5 if self._window_mode == "5d" else 3


def _make_gui_stub(
    *,
    auto_mode: bool,
    window_mode: str,
    target_date: date,
    start: str = "",
    end: str = "",
    engine: str = "python",
) -> ZipFlowGui:
    gui = object.__new__(ZipFlowGui)
    gui.run_mode_var = DummyVar("解析雨量データ")
    gui.input_zipdir_var = DummyVar(r"C:\\data\\zip")
    gui.output_dir_var = DummyVar(r"C:\\out")
    gui.polygon_dir_var = DummyVar(r"C:\\poly")
    gui.enable_log_var = DummyVar(False)
    gui.export_svg_var = DummyVar(False)
    gui.start_date_var = DummyVar(start)
    gui.end_date_var = DummyVar(end)
    gui.compute_engine_var = DummyVar(engine)
    gui.region_vars = {"nishiyoke": DummyVar(True), "yamatogawa": DummyVar(False)}
    gui.output_vars = {"plots_ref": DummyVar(True), "raster": DummyVar(False)}
    gui.graph_kind_vars = {"sum": DummyVar(True), "mean": DummyVar(False)}
    gui.rain_panel = DummyRainPanel(target_dates=[target_date], window_mode=window_mode, auto_mode=auto_mode)
    return gui


@pytest.mark.parametrize(
    ("mode", "expected_start", "expected_end"),
    [
        ("5d", datetime(2024, 1, 1, 0, 0), datetime(2024, 1, 5, 23, 0)),
        ("3d_left", datetime(2024, 1, 1, 0, 0), datetime(2024, 1, 3, 23, 0)),
        ("3d_center", datetime(2024, 1, 2, 0, 0), datetime(2024, 1, 4, 23, 0)),
        ("3d_right", datetime(2024, 1, 3, 0, 0), datetime(2024, 1, 5, 23, 0)),
    ],
)
def test_rain_mode_window_resolution(mode: str, expected_start: datetime, expected_end: datetime) -> None:
    start, end = RainModePanel._resolve_window(None, date(2024, 1, 3), mode)
    assert start == expected_start
    assert end == expected_end


@pytest.mark.parametrize(
    ("window_mode", "expected_reference_base_date"),
    [
        ("3d_left", date(2024, 1, 2)),
        ("3d_right", date(2024, 1, 4)),
    ],
)
def test_build_rain_run_configs_auto_mode_sets_reference_base_date(
    monkeypatch: pytest.MonkeyPatch,
    window_mode: str,
    expected_reference_base_date: date,
) -> None:
    from uc_rainfall_zipflow.gui import app as app_module

    monkeypatch.setattr(app_module, "default_style_profile_path", lambda: Path(r"C:\\missing\\style.json"))
    gui = _make_gui_stub(auto_mode=True, window_mode=window_mode, target_date=date(2024, 1, 3))

    configs, day_count = ZipFlowGui._build_rain_run_configs(gui)

    assert day_count == 3
    assert len(configs) == 1
    config = configs[0]
    assert config.base_date == date(2024, 1, 3)
    assert config.reference_base_date == expected_reference_base_date
    assert config.graph_spans == ("3d",)
    assert config.start_date == expected_reference_base_date - timedelta(days=1)
    assert config.end_date == expected_reference_base_date + timedelta(days=1)
    assert config.engine == "python"


def test_build_rain_run_configs_manual_mode_leaves_reference_base_date_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uc_rainfall_zipflow.gui import app as app_module

    monkeypatch.setattr(app_module, "default_style_profile_path", lambda: Path(r"C:\\missing\\style.json"))
    gui = _make_gui_stub(auto_mode=False, window_mode="5d", target_date=date(2024, 1, 3), start="2024-01-01", end="2024-01-05")

    configs, day_count = ZipFlowGui._build_rain_run_configs(gui)

    assert day_count == 5
    assert len(configs) == 1
    config = configs[0]
    assert config.base_date == date(2024, 1, 3)
    assert config.reference_base_date is None
    assert config.graph_spans == ("5d",)
    assert config.start_date == date(2024, 1, 1)
    assert config.end_date == date(2024, 1, 5)
    assert config.engine == "python"


def test_build_rain_run_configs_uses_selected_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uc_rainfall_zipflow.gui import app as app_module

    monkeypatch.setattr(app_module, "default_style_profile_path", lambda: Path(r"C:\\missing\\style.json"))
    gui = _make_gui_stub(
        auto_mode=False,
        window_mode="5d",
        target_date=date(2024, 1, 3),
        start="2024-01-01",
        end="2024-01-05",
        engine="rust_pyo3",
    )

    configs, _day_count = ZipFlowGui._build_rain_run_configs(gui)

    assert configs[0].engine == "rust_pyo3"


def test_build_rain_run_configs_rejects_invalid_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uc_rainfall_zipflow.gui import app as app_module

    monkeypatch.setattr(app_module, "default_style_profile_path", lambda: Path(r"C:\\missing\\style.json"))
    gui = _make_gui_stub(
        auto_mode=False,
        window_mode="5d",
        target_date=date(2024, 1, 3),
        start="2024-01-01",
        end="2024-01-05",
        engine="rust_subprocess",
    )

    with pytest.raises(ValueError, match="計算エンジンが不正です"):
        ZipFlowGui._build_rain_run_configs(gui)


def test_help_service_returns_bundled_text() -> None:
    assert get_gui_help_text() == DEFAULT_GUI_HELP_TEXT.strip()


def test_app_help_loader_returns_bundled_text() -> None:
    assert _load_gui_help_text_from_candidates() == DEFAULT_GUI_HELP_TEXT.strip()
