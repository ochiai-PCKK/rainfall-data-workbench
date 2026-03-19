from __future__ import annotations

import re
import shutil
import tempfile
import time
import zipfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import rasterio
from rasterio.warp import transform_bounds

from .models import TimeSlot, ZipWindow

_JST_RE = re.compile(r"_JST_(\d{8})_(\d{6})")


def _parse_observed_at(path: Path) -> datetime | None:
    match = _JST_RE.search(path.name)
    if match is None:
        return None
    return datetime.strptime(f"{match.group(1)}{match.group(2)}", "%Y%m%d%H%M%S")


def _cleanup_temp_dir(path: Path, *, retries: int = 8, base_wait: float = 0.15) -> None:
    """Windows のファイルロックを考慮して一時ディレクトリを削除する。"""
    last_error: OSError | None = None
    for attempt in range(retries):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except PermissionError as exc:
            last_error = exc
        except OSError as exc:
            # Windows の EBUSY/EACCES 相当は短時間で解放されることがあるため再試行する。
            if getattr(exc, "winerror", None) in (5, 32):
                last_error = exc
            else:
                raise
        time.sleep(base_wait * (attempt + 1))

    # 最終手段: ここで失敗しても実行結果は壊さない。残骸は次回以降に回収される。
    if last_error is not None:
        shutil.rmtree(path, ignore_errors=True)


@contextmanager
def extract_target_zips(selected: list[ZipWindow]):
    """選定 ZIP を一時展開してルート一覧を返す。"""
    tmp = Path(tempfile.mkdtemp(prefix="uc_rainfall_zipflow_"))
    try:
        roots: list[Path] = []
        for idx, item in enumerate(selected):
            dest = tmp / f"zip_{idx:02d}"
            dest.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(item.path) as zf:
                zf.extractall(dest)
            roots.append(dest)
        yield roots
    finally:
        _cleanup_temp_dir(tmp)


def build_raster_index(extracted_roots: list[Path]) -> dict[datetime, list[Path]]:
    """展開済みルートから JST 時刻 -> TIFF パス候補一覧の索引を作る。"""
    index: dict[datetime, list[Path]] = {}
    for root in extracted_roots:
        for path in root.rglob("*.tif*"):
            if not path.is_file():
                continue
            observed_at = _parse_observed_at(path)
            if observed_at is None:
                continue
            index.setdefault(observed_at, []).append(path)
    if not index:
        raise ValueError("ZIP 内に JST 時刻付き TIFF が見つかりませんでした。")
    return index


def _grid_signature_4326(path: Path) -> tuple[float, float, float, float, float, float]:
    """4326基準での格子シグネチャ (dx, dy, west, south, east, north) を返す。"""
    with rasterio.open(path) as src:
        if src.crs is None:
            raise ValueError(f"CRS が不明な TIFF です: {path}")
        if str(src.crs).upper() == "EPSG:4326":
            west, south, east, north = src.bounds
            dx = abs(float(src.transform.a))
            dy = abs(float(src.transform.e))
            return dx, dy, float(west), float(south), float(east), float(north)
        west, south, east, north = transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=21)
        dx = abs((east - west) / src.width)
        dy = abs((north - south) / src.height)
        return float(dx), float(dy), float(west), float(south), float(east), float(north)


def _signature_distance(
    ref: tuple[float, float, float, float, float, float],
    cur: tuple[float, float, float, float, float, float],
) -> float:
    return sum(abs(a - b) for a, b in zip(ref, cur, strict=True))


def resolve_slot_rasters(*, slots: list[TimeSlot], raster_index: dict[datetime, list[Path]]) -> list[Path]:
    """指定スロット分の TIFF を順序付きで返す（重複時刻は4326格子差が最小の候補を採用）。"""
    resolved: list[Path] = []
    missing: list[str] = []
    signature_cache: dict[Path, tuple[float, float, float, float, float, float]] = {}
    reference_signature: tuple[float, float, float, float, float, float] | None = None
    for slot in slots:
        candidates = raster_index.get(slot.observed_at_jst)
        if not candidates:
            missing.append(slot.observed_at_jst.strftime("%Y-%m-%d %H:%M:%S"))
            continue
        ordered = sorted(candidates, key=lambda p: p.name)
        if len(ordered) == 1:
            chosen = ordered[0]
        elif reference_signature is None:
            chosen = ordered[0]
        else:
            best = None
            best_score = None
            for candidate in ordered:
                signature = signature_cache.get(candidate)
                if signature is None:
                    signature = _grid_signature_4326(candidate)
                    signature_cache[candidate] = signature
                score = _signature_distance(reference_signature, signature)
                if best is None or best_score is None or score < best_score:
                    best = candidate
                    best_score = score
            assert best is not None
            chosen = best

        signature = signature_cache.get(chosen)
        if signature is None:
            signature = _grid_signature_4326(chosen)
            signature_cache[chosen] = signature
        if reference_signature is None:
            reference_signature = signature
        resolved.append(chosen)
    if missing:
        preview = ", ".join(missing[:6])
        suffix = "" if len(missing) <= 6 else f" ... (計{len(missing)}件)"
        raise ValueError(f"必要時刻の TIFF が不足しています: {preview}{suffix}")
    if len(resolved) != len(slots):
        raise ValueError(f"時系列点数が一致しません: expected={len(slots)} actual={len(resolved)}")
    return resolved
