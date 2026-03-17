from __future__ import annotations

from datetime import date
from datetime import datetime
from pathlib import Path

from ..continuity_checker import check_mail_entry_continuity
from ..download_store import DownloadStore
from ..mail_parser import parse_mail_body
from ..mail_parser import split_mail_bodies
from ..models import MailEntry


def ingest_mail_bodies(
    text: str,
    *,
    output_dir: Path,
    expected_start: date | None = None,
    expected_end: date | None = None,
) -> dict[str, object]:
    """貼り付けられたメール本文を取り込み、構造化保存と整合性チェックを行う。"""
    store = DownloadStore(output_dir)
    existing_entries = store.load_mail_entries()
    existing_zip_results = store.load_zip_results()
    latest_zip_result_by_source_id = {result.source_id: result for result in existing_zip_results}
    current_entries_by_window = {
        (entry.period_start, entry.period_end): entry
        for entry in existing_entries
    }
    current_source_ids = {entry.source_id for entry in existing_entries}

    blocks = split_mail_bodies(text)
    if not blocks:
        raise RuntimeError("入力テキストからメール本文を 1 件も検出できませんでした。")

    added_entries: list[MailEntry] = []
    refreshed_entries: list[dict[str, str | None]] = []
    parse_failures: list[dict[str, str]] = []
    duplicate_entries: list[dict[str, str]] = []

    for index, block in enumerate(blocks, start=1):
        try:
            parsed = parse_mail_body(block)
        except ValueError as exc:
            raw_path = store.save_raw_mail_body(block, f"parse_error_{index:04d}")
            parse_failures.append(
                {
                    "index": str(index),
                    "message": str(exc),
                    "raw_body_path": str(raw_path),
                }
            )
            continue

        window = (parsed.period_start, parsed.period_end)
        if parsed.source_id in current_source_ids:
            raw_path = store.save_raw_mail_body(block, parsed.source_id)
            duplicate_entries.append(
                {
                    "index": str(index),
                    "source_id": parsed.source_id,
                    "message": "同じ source_id のメール本文は既に登録済みです。",
                    "raw_body_path": str(raw_path),
                }
            )
            continue

        existing_entry = current_entries_by_window.get(window)
        if existing_entry is not None:
            existing_zip_result = latest_zip_result_by_source_id.get(existing_entry.source_id)
            existing_zip_status = existing_zip_result.status if existing_zip_result is not None else None
            if existing_zip_status in {"failed", "expired"}:
                raw_path = store.save_raw_mail_body(block, parsed.source_id)
                replacement_entry = MailEntry(
                    source_id=parsed.source_id,
                    download_url=parsed.download_url,
                    period_start=parsed.period_start,
                    period_end=parsed.period_end,
                    raw_body_path=raw_path,
                    ingested_at=datetime.now(),
                )
                current_entries_by_window[window] = replacement_entry
                current_source_ids.discard(existing_entry.source_id)
                current_source_ids.add(replacement_entry.source_id)
                refreshed_entries.append(
                    {
                        "index": str(index),
                        "period_start": parsed.period_start.isoformat(),
                        "period_end": parsed.period_end.isoformat(),
                        "old_source_id": existing_entry.source_id,
                        "new_source_id": replacement_entry.source_id,
                        "replaced_zip_status": existing_zip_status,
                        "raw_body_path": str(raw_path),
                    }
                )
                continue

            raw_path = store.save_raw_mail_body(block, parsed.source_id)
            duplicate_entries.append(
                {
                    "index": str(index),
                    "source_id": parsed.source_id,
                    "message": "同じ期間のメール本文は既に登録済みです。",
                    "existing_source_id": existing_entry.source_id,
                    "existing_zip_status": existing_zip_status,
                    "raw_body_path": str(raw_path),
                }
            )
            continue

        raw_path = store.save_raw_mail_body(block, parsed.source_id)
        new_entry = MailEntry(
            source_id=parsed.source_id,
            download_url=parsed.download_url,
            period_start=parsed.period_start,
            period_end=parsed.period_end,
            raw_body_path=raw_path,
            ingested_at=datetime.now(),
        )
        current_entries_by_window[window] = new_entry
        current_source_ids.add(new_entry.source_id)
        added_entries.append(new_entry)

    all_entries = sorted(
        current_entries_by_window.values(),
        key=lambda item: (item.period_start, item.period_end, item.source_id),
    )
    continuity_issues = check_mail_entry_continuity(
        all_entries,
        expected_start=expected_start,
        expected_end=expected_end,
    )

    entries_path = store.save_mail_entries(all_entries)
    issues_path = store.save_continuity_issues(continuity_issues)
    summary = {
        "input_block_count": len(blocks),
        "existing_entry_count": len(existing_entries),
        "added_entry_count": len(added_entries),
        "refreshed_entry_count": len(refreshed_entries),
        "total_entry_count": len(all_entries),
        "parse_failure_count": len(parse_failures),
        "duplicate_count": len(duplicate_entries),
        "warning_count": len(continuity_issues),
        "expected_start": expected_start.isoformat() if expected_start else None,
        "expected_end": expected_end.isoformat() if expected_end else None,
        "entries_path": str(entries_path),
        "issues_path": str(issues_path),
        "added_entries": [entry.to_dict() for entry in added_entries],
        "refreshed_entries": refreshed_entries,
        "parse_failures": parse_failures,
        "duplicates": duplicate_entries,
        "warning_examples": [issue.to_dict() for issue in continuity_issues],
    }
    summary_path = store.save_mail_ingest_summary(summary)
    summary["summary_path"] = str(summary_path)
    return summary
