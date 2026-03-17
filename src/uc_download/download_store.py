from __future__ import annotations

import json
from dataclasses import is_dataclass
from datetime import date
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import ContinuityIssue
from .models import MailEntry
from .models import ZipDownloadResult


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


class DownloadStore:
    """メール取り込み結果と後段ダウンロード結果を保存する。"""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.mail_ingest_dir = output_dir / "mail_ingest"
        self.raw_mail_dir = self.mail_ingest_dir / "raw"
        self.mail_entries_path = self.mail_ingest_dir / "mail_entries.json"
        self.continuity_issues_path = self.mail_ingest_dir / "continuity_issues.json"
        self.mail_ingest_summary_path = self.mail_ingest_dir / "mail_ingest_summary.json"
        self.zip_results_path = self.output_dir / "zip_results.json"
        self.zip_fetch_summary_path = self.output_dir / "zip_fetch_summary.json"
        self.download_manifest_path = output_dir / "download_manifest.json"

        self.mail_ingest_dir.mkdir(parents=True, exist_ok=True)
        self.raw_mail_dir.mkdir(parents=True, exist_ok=True)

    def load_mail_entries(self) -> list[MailEntry]:
        """既存のメールエントリ一覧を読み込む。"""
        if not self.mail_entries_path.exists():
            return []

        payload = json.loads(self.mail_entries_path.read_text(encoding="utf-8"))
        entries: list[MailEntry] = []
        for item in payload:
            entries.append(
                MailEntry(
                    source_id=str(item["source_id"]),
                    download_url=str(item["download_url"]),
                    period_start=date.fromisoformat(str(item["period_start"])),
                    period_end=date.fromisoformat(str(item["period_end"])),
                    raw_body_path=Path(str(item["raw_body_path"])),
                    ingested_at=datetime.fromisoformat(str(item["ingested_at"])),
                )
            )
        return entries

    def save_raw_mail_body(self, text: str, stem: str) -> Path:
        """メール本文を raw テキストとして保存する。"""
        safe_stem = "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in stem)
        path = self.raw_mail_dir / f"{safe_stem}.txt"
        if path.exists():
            suffix = 1
            while True:
                candidate = self.raw_mail_dir / f"{safe_stem}_{suffix:03d}.txt"
                if not candidate.exists():
                    path = candidate
                    break
                suffix += 1
        path.write_text(text, encoding="utf-8")
        return path

    def save_mail_entries(self, entries: list[MailEntry]) -> Path:
        """メールエントリ一覧を保存する。"""
        payload = [entry.to_dict() for entry in entries]
        return self._write_json(self.mail_entries_path, payload)

    def save_continuity_issues(self, issues: list[ContinuityIssue]) -> Path:
        """整合性チェック結果を保存する。"""
        payload = [issue.to_dict() for issue in issues]
        return self._write_json(self.continuity_issues_path, payload)

    def save_mail_ingest_summary(self, summary: dict[str, Any]) -> Path:
        """メール取り込みサマリを保存する。"""
        payload = {
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "summary": _serialize(summary),
        }
        return self._write_json(self.mail_ingest_summary_path, payload)

    def load_zip_results(self) -> list[ZipDownloadResult]:
        """既存の ZIP ダウンロード結果を読み込む。"""
        if not self.zip_results_path.exists():
            return []

        payload = json.loads(self.zip_results_path.read_text(encoding="utf-8"))
        results: list[ZipDownloadResult] = []
        for item in payload:
            results.append(
                ZipDownloadResult(
                    source_id=str(item["source_id"]),
                    download_url=str(item["download_url"]),
                    period_start=date.fromisoformat(str(item["period_start"])),
                    period_end=date.fromisoformat(str(item["period_end"])),
                    zip_path=Path(str(item["zip_path"])) if item.get("zip_path") else None,
                    status=str(item["status"]),
                    http_status=int(item["http_status"]) if item.get("http_status") is not None else None,
                    downloaded_at=datetime.fromisoformat(str(item["downloaded_at"]))
                    if item.get("downloaded_at")
                    else None,
                    message=str(item["message"]) if item.get("message") is not None else None,
                    response_preview=str(item["response_preview"]) if item.get("response_preview") is not None else None,
                )
            )
        return results

    def save_zip_results(self, results: list[ZipDownloadResult]) -> Path:
        """ZIP ダウンロード結果一覧を保存する。"""
        payload = [result.to_dict() for result in results]
        return self._write_json(self.zip_results_path, payload)

    def save_zip_fetch_summary(self, summary: dict[str, Any]) -> Path:
        """ZIP 取得サマリを保存する。"""
        payload = {
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "summary": _serialize(summary),
        }
        return self._write_json(self.zip_fetch_summary_path, payload)

    def save_download_manifest(self, manifest: list[dict[str, Any]]) -> Path:
        """統合 manifest を保存する。"""
        return self._write_json(self.download_manifest_path, manifest)

    def _write_json(self, path: Path, payload: Any) -> Path:
        path.write_text(json.dumps(_serialize(payload), ensure_ascii=False, indent=2), encoding="utf-8")
        return path
