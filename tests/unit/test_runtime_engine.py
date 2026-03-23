from __future__ import annotations

import numpy as np
import pytest

from uc_rainfall_zipflow.errors import ZipFlowError
from uc_rainfall_zipflow.runtime_engine import compute_weighted_stats


def test_compute_weighted_stats_python_engine() -> None:
    data = np.array([[1.0, 2.0], [3.0, -9999.0]], dtype=float)
    weights = np.array([[1.0, 1.0], [2.0, 2.0]], dtype=float)

    out = compute_weighted_stats(data=data, weights=weights, engine="python")

    assert out.weighted_sum == pytest.approx(9.0)
    assert out.valid_weight == pytest.approx(4.0)
    assert out.total_weight == pytest.approx(6.0)
    assert out.coverage_ratio == pytest.approx(4.0 / 6.0)
    assert out.weighted_mean == pytest.approx(9.0 / 4.0)


def test_compute_weighted_stats_rejects_unknown_engine() -> None:
    data = np.zeros((2, 2), dtype=float)
    weights = np.ones((2, 2), dtype=float)
    with pytest.raises(ZipFlowError, match="未対応の計算エンジンです"):
        compute_weighted_stats(data=data, weights=weights, engine="rust")


def test_compute_weighted_stats_rust_pyo3_requires_module(monkeypatch: pytest.MonkeyPatch) -> None:
    import uc_rainfall_zipflow.runtime_engine as runtime_engine

    monkeypatch.setattr(runtime_engine, "_PYO3_MODULE", None)

    def _raise(_name: str):
        raise ModuleNotFoundError("no module named weighted_core_pyo3")

    monkeypatch.setattr(runtime_engine.importlib, "import_module", _raise)

    data = np.zeros((2, 2), dtype=float)
    weights = np.ones((2, 2), dtype=float)
    with pytest.raises(ZipFlowError, match="weighted_core_pyo3"):
        compute_weighted_stats(data=data, weights=weights, engine="rust_pyo3")


def test_compute_weighted_stats_rust_pyo3_accepts_float32_input() -> None:
    pytest.importorskip("weighted_core_pyo3")
    data = np.array([[1.0, 2.0], [3.0, -9999.0]], dtype=np.float32)
    weights = np.array([[1.0, 1.0], [2.0, 2.0]], dtype=np.float32)

    out = compute_weighted_stats(data=data, weights=weights, engine="rust_pyo3")

    assert out.weighted_sum == pytest.approx(9.0)
    assert out.valid_weight == pytest.approx(4.0)
    assert out.total_weight == pytest.approx(6.0)
