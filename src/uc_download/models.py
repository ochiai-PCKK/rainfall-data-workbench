from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class BBox:
    """ダウンロード要求に使う緯度経度範囲。"""

    south: float
    north: float
    west: float
    east: float

    def expanded(self, pad_deg: float) -> "BBox":
        """各辺へ余白を加えた bbox を返す。"""
        return BBox(
            south=max(20.000001, self.south - pad_deg),
            north=min(47.999999, self.north + pad_deg),
            west=max(118.000001, self.west - pad_deg),
            east=min(149.999999, self.east + pad_deg),
        )

    def to_dict(self) -> dict[str, float]:
        """JSON 向けに辞書化する。"""
        return {
            "south": self.south,
            "north": self.north,
            "west": self.west,
            "east": self.east,
        }

    def is_close(self, other: "BBox", *, tolerance: float = 1e-6) -> bool:
        """他の bbox と許容誤差付きで一致するかを返す。"""
        return (
            abs(self.south - other.south) <= tolerance
            and abs(self.north - other.north) <= tolerance
            and abs(self.west - other.west) <= tolerance
            and abs(self.east - other.east) <= tolerance
        )


@dataclass(frozen=True)
class RequestWindow:
    """1 回の要求に対応する期間窓。"""

    start_date: date
    end_date: date
    days: int

    @property
    def label(self) -> str:
        """ログやファイル名用の短い識別子を返す。"""
        return f"{self.start_date:%Y%m%d}_{self.end_date:%Y%m%d}_{self.days}d"

    def to_dict(self) -> dict[str, str | int]:
        """JSON 向けに辞書化する。"""
        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "days": self.days,
        }


@dataclass(frozen=True)
class AcceptanceResult:
    """確認画面での要求受理観測結果。"""

    dialog_seen: bool
    dialog_message: str | None
    ok_clicked: bool
    confirm_tab_closed: bool

    @property
    def accepted(self) -> bool:
        """明示的な受理シグナルが取れたかを返す。"""
        return self.dialog_seen or self.ok_clicked

    @property
    def accepted_candidate(self) -> bool:
        """確認タブ閉鎖のみを観測した暫定成功候補かを返す。"""
        return self.confirm_tab_closed and not self.accepted

    def to_dict(self) -> dict[str, bool | str | None]:
        """JSON 向けに辞書化する。"""
        return {
            "dialog_seen": self.dialog_seen,
            "dialog_message": self.dialog_message,
            "ok_clicked": self.ok_clicked,
            "confirm_tab_closed": self.confirm_tab_closed,
            "accepted": self.accepted,
            "accepted_candidate": self.accepted_candidate,
        }


@dataclass(frozen=True)
class RunConfig:
    """CLI 実行時の設定値。"""

    login_url: str
    parameter_url: str
    email: str
    bbox_mode: str
    bbox: BBox
    output_dir: Path
    downloads_dir: Path
    headless: bool
    wait_for_login_seconds: float
    wait_for_ok_seconds: float
    wait_for_page_ready_seconds: float
    request_interval_seconds: float

    def to_dict(self) -> dict[str, object]:
        """JSON 向けに辞書化する。"""
        return {
            "login_url": self.login_url,
            "parameter_url": self.parameter_url,
            "email": self.email,
            "bbox_mode": self.bbox_mode,
            "bbox": self.bbox.to_dict(),
            "output_dir": str(self.output_dir),
            "downloads_dir": str(self.downloads_dir),
            "headless": self.headless,
            "wait_for_login_seconds": self.wait_for_login_seconds,
            "wait_for_ok_seconds": self.wait_for_ok_seconds,
            "wait_for_page_ready_seconds": self.wait_for_page_ready_seconds,
            "request_interval_seconds": self.request_interval_seconds,
        }


@dataclass(frozen=True)
class RequestResult:
    """1 期間ぶんの実行結果。"""

    window: RequestWindow
    accepted: bool
    accepted_candidate: bool
    final_url: str | None
    parameter_page_detected: bool
    confirm_page_detected: bool
    parameter_bbox: dict[str, float] | None
    confirm_bbox: dict[str, float] | None
    dialog_seen: bool
    ok_clicked: bool
    confirm_tab_closed: bool
    screenshot_paths: tuple[Path, ...]
    message: str | None
    started_at: datetime
    finished_at: datetime

    @property
    def failed(self) -> bool:
        """失敗したかを返す。"""
        return not self.accepted and not self.accepted_candidate

    @property
    def status(self) -> str:
        """状態文字列を返す。"""
        if self.accepted:
            return "accepted"
        if self.accepted_candidate:
            return "accepted_candidate"
        return "failed"

    def to_dict(self) -> dict[str, object]:
        """JSON 向けに辞書化する。"""
        return {
            "window": self.window.to_dict(),
            "accepted": self.accepted,
            "accepted_candidate": self.accepted_candidate,
            "failed": self.failed,
            "status": self.status,
            "final_url": self.final_url,
            "parameter_page_detected": self.parameter_page_detected,
            "confirm_page_detected": self.confirm_page_detected,
            "parameter_bbox": self.parameter_bbox,
            "confirm_bbox": self.confirm_bbox,
            "dialog_seen": self.dialog_seen,
            "ok_clicked": self.ok_clicked,
            "confirm_tab_closed": self.confirm_tab_closed,
            "screenshot_paths": [str(path) for path in self.screenshot_paths],
            "message": self.message,
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "finished_at": self.finished_at.isoformat(timespec="seconds"),
        }
