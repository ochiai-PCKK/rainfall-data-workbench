from __future__ import annotations

import json
from pathlib import Path

from ..download_store import DownloadStore
from ..models import MailEntry
from ..models import ZipDownloadResult
from ..zip_downloader import download_zip_from_mail_entry


def fetch_zips(
    *,
    output_dir: Path,
    downloads_dir: Path,
    status_filter: str = "pending",
    timeout_seconds: float = 120.0,
    limit: int | None = None,
) -> dict[str, object]:
    """保存済みメールエントリから ZIP を取得し、manifest を更新する。"""
    store = DownloadStore(output_dir)
    mail_entries = store.load_mail_entries()
    existing_results = store.load_zip_results()
    latest_result_by_source_id = {result.source_id: result for result in existing_results}

    target_entries = _select_target_entries(mail_entries, latest_result_by_source_id, status_filter=status_filter)
    if limit is not None:
        target_entries = target_entries[:limit]
    updated_results = dict(latest_result_by_source_id)

    processed_results: list[ZipDownloadResult] = []
    for entry in target_entries:
        result = download_zip_from_mail_entry(entry, downloads_dir=downloads_dir, timeout_seconds=timeout_seconds)
        updated_results[entry.source_id] = result
        processed_results.append(result)

    all_results = sorted(updated_results.values(), key=lambda item: (item.period_start, item.period_end, item.source_id))
    zip_results_path = store.save_zip_results(all_results)
    manifest = _build_download_manifest(output_dir=output_dir, mail_entries=mail_entries, zip_results=all_results)
    manifest_path = store.save_download_manifest(manifest)

    summary = {
        "status_filter": status_filter,
        "limit": limit,
        "mail_entry_count": len(mail_entries),
        "target_entry_count": len(target_entries),
        "downloaded_count": sum(1 for item in processed_results if item.status == "downloaded"),
        "failed_count": sum(1 for item in processed_results if item.status == "failed"),
        "expired_count": sum(1 for item in processed_results if item.status == "expired"),
        "already_exists_count": sum(1 for item in processed_results if item.status == "already_exists"),
        "zip_results_path": str(zip_results_path),
        "manifest_path": str(manifest_path),
        "result_examples": _build_result_examples(processed_results),
    }
    summary_path = store.save_zip_fetch_summary(summary)
    summary["summary_path"] = str(summary_path)
    return summary


def _select_target_entries(
    mail_entries: list[MailEntry],
    latest_result_by_source_id: dict[str, ZipDownloadResult],
    *,
    status_filter: str,
) -> list[MailEntry]:
    if status_filter == "all":
        return mail_entries
    if status_filter == "failed":
        return [
            entry
            for entry in mail_entries
            if latest_result_by_source_id.get(entry.source_id, None)
            and latest_result_by_source_id[entry.source_id].status == "failed"
        ]
    if status_filter == "expired":
        return [
            entry
            for entry in mail_entries
            if latest_result_by_source_id.get(entry.source_id, None)
            and latest_result_by_source_id[entry.source_id].status == "expired"
        ]
    if status_filter == "pending":
        return [
            entry
            for entry in mail_entries
            if latest_result_by_source_id.get(entry.source_id) is None
            or latest_result_by_source_id[entry.source_id].status not in {"downloaded", "already_exists", "expired"}
        ]
    raise ValueError(f"未知の status_filter です: {status_filter}")


def _build_result_examples(results: list[ZipDownloadResult]) -> list[dict[str, str | None]]:
    examples: list[dict[str, str | None]] = []
    for item in results:
        if item.status not in {"failed", "expired"}:
            continue
        examples.append(
            {
                "source_id": item.source_id,
                "period_start": item.period_start.isoformat(),
                "period_end": item.period_end.isoformat(),
                "status": item.status,
                "message": item.message,
            }
        )
        if len(examples) >= 5:
            break
    return examples


def _build_download_manifest(
    *,
    output_dir: Path,
    mail_entries: list[MailEntry],
    zip_results: list[ZipDownloadResult],
) -> list[dict[str, object]]:
    request_status_map = _load_request_status_map(output_dir / "request_results.json")
    zip_result_map = {item.source_id: item for item in zip_results}
    manifest: list[dict[str, object]] = []

    for entry in sorted(mail_entries, key=lambda item: (item.period_start, item.period_end, item.source_id)):
        request_key = (entry.period_start.isoformat(), entry.period_end.isoformat())
        zip_result = zip_result_map.get(entry.source_id)
        manifest.append(
            {
                "source_id": entry.source_id,
                "window": {
                    "start_date": entry.period_start.isoformat(),
                    "end_date": entry.period_end.isoformat(),
                },
                "request_status": request_status_map.get(request_key),
                "mail_status": "ingested",
                "zip_status": zip_result.status if zip_result else "pending",
                "download_url": entry.download_url,
                "zip_path": str(zip_result.zip_path) if zip_result and zip_result.zip_path else None,
                "http_status": zip_result.http_status if zip_result else None,
                "message": zip_result.message if zip_result else None,
                "response_preview": zip_result.response_preview if zip_result else None,
            }
        )
    return manifest


def _load_request_status_map(path: Path) -> dict[tuple[str, str], str]:
    if not path.exists():
        return {}

    payload = json.loads(path.read_text(encoding="utf-8"))
    result: dict[tuple[str, str], str] = {}
    for item in payload:
        window = item.get("window") or {}
        start_date = window.get("start_date")
        end_date = window.get("end_date")
        status = item.get("status")
        if start_date and end_date and status:
            result[(str(start_date), str(end_date))] = str(status)
    return result
