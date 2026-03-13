from __future__ import annotations

import json
from dataclasses import is_dataclass
from datetime import date
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import Page

from .models import RequestResult
from .models import RequestWindow
from .models import RunConfig


def _serialize(value: Any) -> Any:
    """JSON 保存用に値を再帰的に変換する。"""
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _serialize(value.to_dict())
    if is_dataclass(value):
        return {key: _serialize(getattr(value, key)) for key in value.__dataclass_fields__}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    return value


class ResultStore:
    """実行結果ファイルとスクリーンショットを保存する。"""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.downloads_dir = output_dir / "downloads"
        self.screenshots_dir = output_dir / "screenshots"
        self.period_plan_path = output_dir / "period_plan.json"
        self.run_config_path = output_dir / "run_config.json"
        self.request_results_path = output_dir / "request_results.json"
        self.run_summary_path = output_dir / "run_summary.json"
        self._request_results: list[dict[str, Any]] = []

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

    def save_period_plan(self, windows: list[RequestWindow]) -> Path:
        """期間計画を JSON 保存する。"""
        payload = {
            "window_count": len(windows),
            "first_window": windows[0].to_dict() if windows else None,
            "last_window": windows[-1].to_dict() if windows else None,
            "windows": [window.to_dict() for window in windows],
        }
        return self._write_json(self.period_plan_path, payload)

    def save_run_config(self, config: RunConfig, *, command: str) -> Path:
        """実行設定を JSON 保存する。"""
        payload = {
            "command": command,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "config": config.to_dict(),
        }
        return self._write_json(self.run_config_path, payload)

    def append_request_result(self, result: RequestResult) -> Path:
        """期間ごとの結果を追記しつつ JSON 保存する。"""
        self._request_results.append(result.to_dict())
        return self._write_json(self.request_results_path, self._request_results)

    def save_summary(self, summary: dict[str, Any]) -> Path:
        """実行サマリを保存する。"""
        payload = {
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "summary": _serialize(summary),
        }
        return self._write_json(self.run_summary_path, payload)

    def save_screenshot(self, page: Page, stem: str) -> Path | None:
        """ページのスクリーンショットを保存する。"""
        if page.is_closed():
            return None
        path = self.screenshots_dir / f"{stem}_{datetime.now():%Y%m%d_%H%M%S}.png"
        page.screenshot(path=str(path), full_page=True)
        return path

    def _write_json(self, path: Path, payload: Any) -> Path:
        path.write_text(json.dumps(_serialize(payload), ensure_ascii=False, indent=2), encoding="utf-8")
        return path
