from __future__ import annotations

from datetime import date
from pathlib import Path

from .models import BBox
from .models import RunConfig


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_LOGIN_URL = "https://tools.i-ric.info/login/"
DEFAULT_PARAMETER_URL = "https://tools.i-ric.info/confirm/"
DEFAULT_EMAIL = "yuuta.ochiai@tk.pacific.co.jp"

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "uc_download"
DEFAULT_DOWNLOADS_DIR = DEFAULT_OUTPUT_DIR / "downloads"

DEFAULT_PERIOD_START = date(2010, 1, 2)
DEFAULT_PERIOD_END = date(2025, 12, 31)
DEFAULT_CHUNK_DAYS = 3

DEFAULT_BBOX_PRESET = "yamatogawa"
DEFAULT_BBOX_PAD_DEG = 0.02

DEFAULT_WAIT_FOR_LOGIN_SECONDS = 300.0
DEFAULT_WAIT_FOR_OK_SECONDS = 8.0
DEFAULT_WAIT_FOR_PAGE_READY_SECONDS = 30.0
DEFAULT_REQUEST_INTERVAL_SECONDS = 60.0

PRESET_BBOXES: dict[str, BBox] = {
    "yamatogawa": BBox(34.33633333, 34.78113889, 135.43291667, 135.94752778),
    "higashiyoke": BBox(34.48055556, 34.59694445, 135.55388889, 135.62527778),
    "nishiyoke": BBox(34.40861112, 34.58944446, 135.49055556, 135.57194445),
    "yoke_combined": BBox(34.40861112, 34.59694445, 135.49055556, 135.62527778),
}


def resolve_bbox(
    *,
    explicit_bbox: tuple[float, float, float, float] | None,
    preset_name: str | None,
    pad_deg: float,
) -> BBox:
    """CLI 引数から実際に使う bbox を決定する。"""
    if explicit_bbox is not None:
        return BBox(*explicit_bbox).expanded(pad_deg)

    resolved_preset = preset_name or DEFAULT_BBOX_PRESET
    if resolved_preset not in PRESET_BBOXES:
        available = ", ".join(sorted(PRESET_BBOXES))
        raise ValueError(f"未知の bbox プリセットです: {resolved_preset}. 利用可能: {available}")
    return PRESET_BBOXES[resolved_preset].expanded(pad_deg)


def build_run_config(
    *,
    email: str,
    bbox_mode: str,
    bbox: BBox,
    output_dir: Path,
    downloads_dir: Path,
    headless: bool,
    wait_for_login_seconds: float = DEFAULT_WAIT_FOR_LOGIN_SECONDS,
    wait_for_ok_seconds: float = DEFAULT_WAIT_FOR_OK_SECONDS,
    wait_for_page_ready_seconds: float = DEFAULT_WAIT_FOR_PAGE_READY_SECONDS,
    request_interval_seconds: float = DEFAULT_REQUEST_INTERVAL_SECONDS,
    login_url: str = DEFAULT_LOGIN_URL,
    parameter_url: str = DEFAULT_PARAMETER_URL,
) -> RunConfig:
    """実行設定オブジェクトを構築する。"""
    return RunConfig(
        login_url=login_url,
        parameter_url=parameter_url,
        email=email,
        bbox_mode=bbox_mode,
        bbox=bbox,
        output_dir=output_dir,
        downloads_dir=downloads_dir,
        headless=headless,
        wait_for_login_seconds=wait_for_login_seconds,
        wait_for_ok_seconds=wait_for_ok_seconds,
        wait_for_page_ready_seconds=wait_for_page_ready_seconds,
        request_interval_seconds=request_interval_seconds,
    )
