"""重み付き集計の実行エンジン切替（python / rust_pyo3）。"""
from __future__ import annotations

import importlib
from dataclasses import dataclass

import numpy as np

from .errors import ZipFlowError
from .spatial_clip import NODATA_VALUE

_SUPPORTED_ENGINES = ("python", "rust_pyo3")
_PYO3_MODULE = None


@dataclass(frozen=True)
class WeightedStats:
    weighted_sum: float
    weighted_mean: float
    valid_weight: float
    total_weight: float
    coverage_ratio: float


def _ensure_pyo3_module():
    global _PYO3_MODULE
    if _PYO3_MODULE is not None:
        return _PYO3_MODULE
    try:
        _PYO3_MODULE = importlib.import_module("weighted_core_pyo3")
    except ModuleNotFoundError as exc:
        raise ZipFlowError(
            "rust_pyo3 エンジンを使用するには `weighted_core_pyo3` のインストールが必要です。"
            "（例: uv run maturin develop --manifest-path rust/weighted_core_pyo3/Cargo.toml）",
            exit_code=2,
        ) from exc
    return _PYO3_MODULE


def _compute_python(*, data: np.ndarray, weights: np.ndarray) -> WeightedStats:
    positive = weights > 0.0
    total_weight = float(np.sum(weights[positive]))
    if total_weight <= 0.0:
        raise ZipFlowError("流域内重みが0です。", exit_code=5)
    valid = (data != NODATA_VALUE) & np.isfinite(data) & positive
    valid_weight = float(np.sum(weights[valid]))
    coverage = valid_weight / total_weight
    if valid_weight <= 0.0:
        return WeightedStats(
            weighted_sum=float("nan"),
            weighted_mean=float("nan"),
            valid_weight=valid_weight,
            total_weight=total_weight,
            coverage_ratio=coverage,
        )
    weighted_sum = float(np.sum(data[valid] * weights[valid]))
    weighted_mean = weighted_sum / valid_weight
    return WeightedStats(
        weighted_sum=weighted_sum,
        weighted_mean=weighted_mean,
        valid_weight=valid_weight,
        total_weight=total_weight,
        coverage_ratio=coverage,
    )


def _compute_rust_pyo3(*, data: np.ndarray, weights: np.ndarray) -> WeightedStats:
    module = _ensure_pyo3_module()
    # PyO3 側は f64 の C-contiguous 配列を受け取るため、ここで正規化する。
    frames_3d = np.ascontiguousarray(np.expand_dims(data, axis=0), dtype=np.float64)
    weights_2d = np.ascontiguousarray(weights, dtype=np.float64)
    try:
        out = module.compute_weighted_core(frames_3d, weights_2d, float(NODATA_VALUE))
    except Exception as exc:  # noqa: BLE001
        raise ZipFlowError(
            "rust_pyo3 エンジン呼び出しに失敗しました。"
            f" frames_dtype={frames_3d.dtype} weights_dtype={weights_2d.dtype}",
            exit_code=2,
        ) from exc
    weighted_sum = out["weighted_sum_mm"][0]
    weighted_mean = out["weighted_mean_mm"][0]
    coverage = out["coverage_ratio"][0]
    valid_weight = out["valid_weight"][0]
    total_weight = out["total_weight"][0]
    return WeightedStats(
        weighted_sum=float("nan") if weighted_sum is None else float(weighted_sum),
        weighted_mean=float("nan") if weighted_mean is None else float(weighted_mean),
        valid_weight=0.0 if valid_weight is None else float(valid_weight),
        total_weight=0.0 if total_weight is None else float(total_weight),
        coverage_ratio=float("nan") if coverage is None else float(coverage),
    )


def compute_weighted_stats(*, data: np.ndarray, weights: np.ndarray, engine: str) -> WeightedStats:
    """指定エンジンで重み付き統計を1時刻分計算する。"""
    if engine not in _SUPPORTED_ENGINES:
        raise ZipFlowError(f"未対応の計算エンジンです: {engine}", exit_code=2)
    if engine == "python":
        return _compute_python(data=data, weights=weights)
    return _compute_rust_pyo3(data=data, weights=weights)
