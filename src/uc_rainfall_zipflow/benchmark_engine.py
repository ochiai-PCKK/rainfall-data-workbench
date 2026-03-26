"""Python / Rust(subprocess) / Rust(PyO3) の比較ベンチ実行モジュール。

本モジュールは、まず比較基盤を独立で進化させるために
`application.py` とは切り離して実装している。
"""
from __future__ import annotations

import csv
import ctypes
import importlib
import json
import math
import os
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np

from .errors import ZipFlowError
from .spatial_clip import NODATA_VALUE

_PROCESS_QUERY_INFORMATION = 0x0400
_PROCESS_VM_READ = 0x0010


class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


@dataclass(frozen=True)
class _RunRow:
    """`runs.csv` に1行として出力する計測レコード。"""

    engine: str
    run_no: int
    wall_time_ms: float
    cpu_time_ms: float
    peak_rss_mb: float
    output_rows: int
    max_abs_diff: float
    rmse: float


def _process_rss_bytes(pid: int) -> int:
    """Windows上で対象プロセスの現在RSS(WorkingSet)をバイトで返す。"""

    k32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    handle = k32.OpenProcess(_PROCESS_QUERY_INFORMATION | _PROCESS_VM_READ, False, pid)
    if not handle:
        return 0
    try:
        counters = _PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS)
        ok = psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
        if not ok:
            return 0
        return int(counters.WorkingSetSize)
    finally:
        k32.CloseHandle(handle)


def _run_with_self_memory_probe(
    fn: Callable[[], dict[str, np.ndarray]],
) -> tuple[dict[str, np.ndarray], float, float, float]:
    """関数実行中にRSSをポーリングし、結果・時間・ピークRSSを返す。"""

    peak = 0
    stop = threading.Event()

    def probe() -> None:
        nonlocal peak
        while not stop.is_set():
            peak = max(peak, _process_rss_bytes(os.getpid()))
            time.sleep(0.005)

    t = threading.Thread(target=probe, daemon=True)
    t.start()
    start_wall = time.perf_counter()
    start_cpu = time.process_time()
    try:
        output = fn()
    finally:
        stop.set()
        t.join(timeout=0.2)
    wall_ms = (time.perf_counter() - start_wall) * 1000.0
    cpu_ms = (time.process_time() - start_cpu) * 1000.0
    peak_mb = peak / (1024 * 1024)
    return output, wall_ms, cpu_ms, peak_mb


def _compute_weighted_core_python(*, frames: np.ndarray, weights: np.ndarray, nodata: float) -> dict[str, np.ndarray]:
    """重み付き集計のPython/NumPy基準実装。"""

    positive = weights > 0.0
    total_weight = float(np.sum(weights[positive]))
    t_count = int(frames.shape[0])
    sum_out = np.full(t_count, np.nan, dtype=np.float64)
    mean_out = np.full(t_count, np.nan, dtype=np.float64)
    coverage_out = np.full(t_count, np.nan, dtype=np.float64)
    valid_weight_out = np.zeros(t_count, dtype=np.float64)
    for t in range(t_count):
        layer = frames[t]
        valid = (layer != nodata) & np.isfinite(layer) & positive
        valid_weight = float(np.sum(weights[valid]))
        valid_weight_out[t] = valid_weight
        if total_weight > 0.0:
            coverage_out[t] = valid_weight / total_weight
        if valid_weight <= 0.0:
            continue
        weighted_sum = float(np.sum(layer[valid] * weights[valid]))
        sum_out[t] = weighted_sum
        mean_out[t] = weighted_sum / valid_weight
    return {
        "weighted_sum_mm": sum_out,
        "weighted_mean_mm": mean_out,
        "coverage_ratio": coverage_out,
        "valid_weight": valid_weight_out,
        "total_weight": np.array([total_weight], dtype=np.float64),
    }


def _to_nullable_list(values: np.ndarray) -> list[float | None]:
    """float配列をJSON互換のリストへ変換する（NaN -> None）。"""

    out: list[float | None] = []
    for v in values:
        fv = float(v)
        out.append(None if math.isnan(fv) else fv)
    return out


def _from_nullable_list(values: list[float | None] | np.ndarray) -> np.ndarray:
    """JSON互換リストをfloat配列へ戻す（None -> NaN）。"""

    return np.array([np.nan if v is None else float(v) for v in values], dtype=np.float64)


def _resolve_cargo_exe() -> str:
    """cargo実行ファイルのパスを解決する（PATHフォールバックあり）。"""

    cargo_path = Path.home() / ".cargo" / "bin" / "cargo.exe"
    if cargo_path.exists():
        return str(cargo_path)
    return "cargo"


def _build_rust_binary(*, manifest_path: Path) -> Path:
    """subprocess版Rustベンチ実行ファイルをビルドしてパスを返す。"""

    cargo = _resolve_cargo_exe()
    target_dir = Path(tempfile.gettempdir()) / "uc_weighted_core_target"
    target_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(target_dir)
    cmd = [cargo, "build", "--release", "-j", "1", "--manifest-path", str(manifest_path)]
    proc = subprocess.run(cmd, capture_output=True, env=env)
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace")
        raise ZipFlowError(f"Rustビルドに失敗しました:\n{stderr}", exit_code=2)
    exe_name = manifest_path.parent.name + ".exe"
    binary = target_dir / "release" / exe_name
    if not binary.exists():
        raise ZipFlowError(f"Rust実行ファイルが見つかりません: {binary}", exit_code=2)
    return binary


def _resolve_rust_binary(
    *,
    manifest_path: Path,
    force_rebuild: bool,
) -> Path:
    """強制再ビルド指定またはソース更新時のみRustを再ビルドする。"""

    target_dir = Path(tempfile.gettempdir()) / "uc_weighted_core_target"
    exe_name = manifest_path.parent.name + ".exe"
    binary = target_dir / "release" / exe_name
    if force_rebuild:
        return _build_rust_binary(manifest_path=manifest_path)
    if not binary.exists():
        return _build_rust_binary(manifest_path=manifest_path)
    # ソース更新時のみ再ビルドする（Cargo.toml, src/*.rs）
    latest_src_mtime = max(
        [manifest_path.stat().st_mtime]
        + [p.stat().st_mtime for p in (manifest_path.parent / "src").glob("*.rs")],
    )
    if binary.stat().st_mtime < latest_src_mtime:
        return _build_rust_binary(manifest_path=manifest_path)
    return binary


def _run_rust_core(
    *,
    binary_path: Path,
    frames: np.ndarray,
    weights: np.ndarray,
    nodata: float,
) -> tuple[dict[str, np.ndarray], float, float, float]:
    """Rust subprocessバックエンドを実行する。

    配列は一時 `.npy` で受け渡し、JSONシリアライズ負荷を避ける。
    """

    with tempfile.TemporaryDirectory(prefix="uc_zipflow_bench_") as td:
        tmp_dir = Path(td)
        weights_path = tmp_dir / "weights.npy"
        frames_path = tmp_dir / "frames.npy"
        out_path = tmp_dir / "result.json"
        np.save(weights_path, weights)
        np.save(frames_path, frames)

        start_wall = time.perf_counter()
        start_cpu = time.process_time()
        proc = subprocess.Popen(
            [
                str(binary_path),
                "--weights",
                str(weights_path),
                "--frames",
                str(frames_path),
                "--out",
                str(out_path),
                "--nodata",
                str(float(nodata)),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        peak = 0
        try:
            while proc.poll() is None:
                peak = max(peak, _process_rss_bytes(proc.pid))
                time.sleep(0.005)
            stderr = proc.stderr.read() if proc.stderr else b""
        finally:
            if proc.stdout:
                proc.stdout.close()
            if proc.stderr:
                proc.stderr.close()
        wall_ms = (time.perf_counter() - start_wall) * 1000.0
        cpu_ms = (time.process_time() - start_cpu) * 1000.0
        peak_mb = peak / (1024 * 1024)
        if proc.returncode != 0:
            err_text = stderr.decode("utf-8", errors="replace")
            raise ZipFlowError(f"Rust実行に失敗しました (code={proc.returncode}):\n{err_text}", exit_code=2)
        if not out_path.exists():
            raise ZipFlowError("Rust実行結果ファイルが生成されませんでした。", exit_code=2)
        data = json.loads(out_path.read_text(encoding="utf-8"))
    return {
        "weighted_sum_mm": _from_nullable_list(data["weighted_sum_mm"]),
        "weighted_mean_mm": _from_nullable_list(data["weighted_mean_mm"]),
        "coverage_ratio": _from_nullable_list(data["coverage_ratio"]),
        "valid_weight": _from_nullable_list(data["valid_weight"]),
        "total_weight": _from_nullable_list(data["total_weight"]),
    }, wall_ms, cpu_ms, peak_mb


def _ensure_pyo3_module(
    *,
    manifest_path: Path,
    force_rebuild: bool,
):
    """必要時のみmaturinでPyO3拡張をビルドしてimportする。"""

    module_name = "weighted_core_pyo3"
    if not force_rebuild:
        try:
            return importlib.import_module(module_name)
        except ModuleNotFoundError:
            pass
    cmd = [
        sys.executable,
        "-m",
        "maturin",
        "develop",
        "--release",
        "--manifest-path",
        str(manifest_path),
        "-q",
    ]
    env = os.environ.copy()
    cargo_bin = str(Path.home() / ".cargo" / "bin")
    env["PATH"] = cargo_bin + os.pathsep + env.get("PATH", "")
    proc = subprocess.run(cmd, capture_output=True, env=env)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace")
        raise ZipFlowError(f"PyO3ビルドに失敗しました:\n{err}", exit_code=2)
    importlib.invalidate_caches()
    return importlib.import_module(module_name)


def _run_pyo3_core(
    *,
    module,
    frames: np.ndarray,
    weights: np.ndarray,
    nodata: float,
) -> tuple[dict[str, np.ndarray], float, float, float]:
    """PyO3バックエンドを同一プロセスで実行し、Python同様に計測する。"""

    output, wall_ms, cpu_ms, peak_mb = _run_with_self_memory_probe(
        lambda: module.compute_weighted_core(frames, weights, float(nodata))
    )
    return {
        "weighted_sum_mm": _from_nullable_list(output["weighted_sum_mm"]),
        "weighted_mean_mm": _from_nullable_list(output["weighted_mean_mm"]),
        "coverage_ratio": _from_nullable_list(output["coverage_ratio"]),
        "valid_weight": _from_nullable_list(output["valid_weight"]),
        "total_weight": _from_nullable_list(output["total_weight"]),
    }, wall_ms, cpu_ms, peak_mb


def _diff_metrics(expected: dict[str, np.ndarray], actual: dict[str, np.ndarray]) -> tuple[float, float]:
    """比較可能な有限値のみで最大絶対誤差とRMSEを返す。"""

    keys = ("weighted_sum_mm", "weighted_mean_mm", "coverage_ratio")
    all_diff: list[np.ndarray] = []
    for key in keys:
        a = expected[key]
        b = actual[key]
        mask = np.isfinite(a) & np.isfinite(b)
        if not np.any(mask):
            continue
        all_diff.append(np.abs(a[mask] - b[mask]))
    if not all_diff:
        return 0.0, 0.0
    merged = np.concatenate(all_diff)
    max_abs = float(np.max(merged))
    rmse = float(np.sqrt(np.mean(merged**2)))
    return max_abs, rmse


def run_core_benchmark(
    *,
    output_root: Path,
    repeat: int,
    warmup: int,
    seed: int,
    slots: int,
    rows: int,
    cols: int,
    rust_manifest: Path,
    force_rebuild: bool = False,
    pyo3_manifest: Path | None = None,
    enable_pyo3: bool = False,
    force_rebuild_pyo3: bool = False,
) -> dict[str, object]:
    """コアベンチを実行し、レポートを保存する。

    シナリオ: 固定seedの合成テンソルで重み付き集計コアを比較。
    出力: `runs.csv`, `summary.json`, `score.json`。
    """

    if repeat <= 0:
        raise ZipFlowError("--repeat は 1 以上を指定してください。", exit_code=2)
    if warmup < 0:
        raise ZipFlowError("--warmup は 0 以上を指定してください。", exit_code=2)
    rng = np.random.default_rng(seed)
    weights = rng.random((rows, cols), dtype=np.float64)
    weights[rng.random((rows, cols)) < 0.35] = 0.0
    frames = rng.random((slots, rows, cols), dtype=np.float64) * 80.0
    frames[rng.random((slots, rows, cols)) < 0.02] = NODATA_VALUE

    rust_binary = _resolve_rust_binary(manifest_path=rust_manifest, force_rebuild=force_rebuild)
    for _ in range(warmup):
        _compute_weighted_core_python(frames=frames, weights=weights, nodata=NODATA_VALUE)
        _run_rust_core(binary_path=rust_binary, frames=frames, weights=weights, nodata=NODATA_VALUE)

    rows_out: list[_RunRow] = []
    baseline: dict[str, np.ndarray] | None = None
    pyo3_module = None
    if enable_pyo3:
        if pyo3_manifest is None:
            raise ZipFlowError("enable_pyo3=True の場合は pyo3_manifest が必要です。", exit_code=2)
        pyo3_module = _ensure_pyo3_module(manifest_path=pyo3_manifest, force_rebuild=force_rebuild_pyo3)
    for i in range(1, repeat + 1):
        py_out, py_wall, py_cpu, py_peak = _run_with_self_memory_probe(
            lambda: _compute_weighted_core_python(frames=frames, weights=weights, nodata=NODATA_VALUE)
        )
        if baseline is None:
            baseline = py_out
        py_max_abs, py_rmse = _diff_metrics(baseline, py_out)
        rows_out.append(
            _RunRow(
                engine="python",
                run_no=i,
                wall_time_ms=py_wall,
                cpu_time_ms=py_cpu,
                peak_rss_mb=py_peak,
                output_rows=slots,
                max_abs_diff=py_max_abs,
                rmse=py_rmse,
            )
        )
        if pyo3_module is not None:
            pyo3_out, pyo3_wall, pyo3_cpu, pyo3_peak = _run_pyo3_core(
                module=pyo3_module,
                frames=frames,
                weights=weights,
                nodata=NODATA_VALUE,
            )
            pyo3_max_abs, pyo3_rmse = _diff_metrics(baseline, pyo3_out)
            rows_out.append(
                _RunRow(
                    engine="rust_pyo3",
                    run_no=i,
                    wall_time_ms=pyo3_wall,
                    cpu_time_ms=pyo3_cpu,
                    peak_rss_mb=pyo3_peak,
                    output_rows=slots,
                    max_abs_diff=pyo3_max_abs,
                    rmse=pyo3_rmse,
                )
            )

        rs_out, rs_wall, rs_cpu, rs_peak = _run_rust_core(
            binary_path=rust_binary,
            frames=frames,
            weights=weights,
            nodata=NODATA_VALUE,
        )
        rs_max_abs, rs_rmse = _diff_metrics(baseline, rs_out)
        rows_out.append(
            _RunRow(
                engine="rust",
                run_no=i,
                wall_time_ms=rs_wall,
                cpu_time_ms=rs_cpu,
                peak_rss_mb=rs_peak,
                output_rows=slots,
                max_abs_diff=rs_max_abs,
                rmse=rs_rmse,
            )
        )

    py_runs = [r for r in rows_out if r.engine == "python"]
    rs_runs = [r for r in rows_out if r.engine == "rust"]
    py_wall_med = float(np.median([r.wall_time_ms for r in py_runs]))
    rs_wall_med = float(np.median([r.wall_time_ms for r in rs_runs]))
    py_mem_med = float(np.median([r.peak_rss_mb for r in py_runs]))
    rs_mem_med = float(np.median([r.peak_rss_mb for r in rs_runs]))
    speed_score = py_wall_med / rs_wall_med if rs_wall_med > 0.0 else float("inf")
    memory_score = py_mem_med / rs_mem_med if rs_mem_med > 0.0 else float("inf")
    rust_max_abs = max(r.max_abs_diff for r in rs_runs)
    rust_rmse = max(r.rmse for r in rs_runs)
    accuracy_passed = rust_max_abs <= 1e-6 and rust_rmse <= 1e-7
    total_score = (0.7 * speed_score + 0.3 * memory_score) if accuracy_passed else 0.0

    pyo3_summary: dict[str, object] | None = None
    pyo3_runs = [r for r in rows_out if r.engine == "rust_pyo3"]
    if pyo3_runs:
        # PyO3は「同一プロセスでRust呼び出し」を比較する任意の第3経路。
        pyo3_wall_med = float(np.median([r.wall_time_ms for r in pyo3_runs]))
        pyo3_mem_med = float(np.median([r.peak_rss_mb for r in pyo3_runs]))
        pyo3_speed = py_wall_med / pyo3_wall_med if pyo3_wall_med > 0.0 else float("inf")
        pyo3_memory = py_mem_med / pyo3_mem_med if pyo3_mem_med > 0.0 else float("inf")
        pyo3_max_abs = max(r.max_abs_diff for r in pyo3_runs)
        pyo3_rmse = max(r.rmse for r in pyo3_runs)
        pyo3_acc_passed = pyo3_max_abs <= 1e-6 and pyo3_rmse <= 1e-7
        pyo3_total = (0.7 * pyo3_speed + 0.3 * pyo3_memory) if pyo3_acc_passed else 0.0
        pyo3_summary = {
            "median": {"wall_time_ms": pyo3_wall_med, "peak_rss_mb": pyo3_mem_med},
            "speed_score": pyo3_speed,
            "memory_score": pyo3_memory,
            "total_score": pyo3_total,
            "accuracy": {"max_abs_diff": pyo3_max_abs, "rmse": pyo3_rmse, "passed": pyo3_acc_passed},
        }

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = output_root / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    with (out_dir / "runs.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "engine",
                "run_no",
                "wall_time_ms",
                "cpu_time_ms",
                "peak_rss_mb",
                "output_rows",
                "max_abs_diff",
                "rmse",
            ],
        )
        writer.writeheader()
        for r in rows_out:
            writer.writerow(asdict(r))

    summary = {
        "scenario": "core_weighted",
        "repeat": repeat,
        "warmup": warmup,
        "seed": seed,
        "shape": {"slots": slots, "rows": rows, "cols": cols},
        "python_median": {"wall_time_ms": py_wall_med, "peak_rss_mb": py_mem_med},
        "rust_median": {"wall_time_ms": rs_wall_med, "peak_rss_mb": rs_mem_med},
        "speed_score": speed_score,
        "memory_score": memory_score,
        "total_score": total_score,
        "accuracy": {"max_abs_diff": rust_max_abs, "rmse": rust_rmse, "passed": accuracy_passed},
        "rust_binary": str(rust_binary),
        "rust_pyo3": pyo3_summary,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "score.json").write_text(
        json.dumps(
            {
                "formula": {
                    "speed_score": "python_wall_ms / rust_wall_ms",
                    "memory_score": "python_peak_rss_mb / rust_peak_rss_mb",
                    "total_score": "0.7 * speed_score + 0.3 * memory_score (accuracy passed only)",
                },
                "thresholds": {"max_abs_diff": 1e-6, "rmse": 1e-7},
                "values": {
                    "speed_score": speed_score,
                    "memory_score": memory_score,
                    "total_score": total_score,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"output_dir": str(out_dir), "summary": summary}
