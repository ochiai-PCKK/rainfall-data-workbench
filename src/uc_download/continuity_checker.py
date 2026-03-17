from __future__ import annotations

from datetime import date
from datetime import timedelta

from .models import ContinuityIssue
from .models import MailEntry


def check_mail_entry_continuity(
    entries: list[MailEntry],
    *,
    expected_start: date | None = None,
    expected_end: date | None = None,
) -> list[ContinuityIssue]:
    """メール本文から抽出した期間一覧の整合性を確認する。"""
    issues: list[ContinuityIssue] = []
    sorted_entries = sorted(entries, key=lambda item: (item.period_start, item.period_end, item.source_id))

    if not sorted_entries:
        if expected_start is not None and expected_end is not None and expected_start <= expected_end:
            issues.append(
                ContinuityIssue(
                    issue_type="gap",
                    severity="warning",
                    message=(
                        "期待期間に対するメール本文が 1 件もありません: "
                        f"{expected_start.isoformat()} -> {expected_end.isoformat()}"
                    ),
                    current_period_start=expected_start,
                    current_period_end=expected_end,
                )
            )
        return issues

    first_entry = sorted_entries[0]
    if expected_start is not None and first_entry.period_start > expected_start:
        missing_end = first_entry.period_start - timedelta(days=1)
        issues.append(
            ContinuityIssue(
                issue_type="gap",
                severity="warning",
                message=(
                    "期待開始日から最初の取得期間までに欠落があります: "
                    f"{expected_start.isoformat()} -> {missing_end.isoformat()}"
                ),
                source_id=first_entry.source_id,
                current_period_start=expected_start,
                current_period_end=missing_end,
            )
        )

    seen_source_ids: set[str] = set()
    seen_windows: set[tuple[date, date]] = set()
    previous: MailEntry | None = None

    for entry in sorted_entries:
        if entry.source_id in seen_source_ids:
            issues.append(
                ContinuityIssue(
                    issue_type="duplicate",
                    severity="warning",
                    message=f"同じ source_id が重複しています: {entry.source_id}",
                    source_id=entry.source_id,
                    current_period_start=entry.period_start,
                    current_period_end=entry.period_end,
                )
            )
        seen_source_ids.add(entry.source_id)

        window = (entry.period_start, entry.period_end)
        if window in seen_windows:
            issues.append(
                ContinuityIssue(
                    issue_type="duplicate",
                    severity="warning",
                    message=(
                        "同じデータ期間が重複しています: "
                        f"{entry.period_start.isoformat()} - {entry.period_end.isoformat()}"
                    ),
                    source_id=entry.source_id,
                    current_period_start=entry.period_start,
                    current_period_end=entry.period_end,
                )
            )
        seen_windows.add(window)

        if expected_start is not None and entry.period_start < expected_start:
            issues.append(
                ContinuityIssue(
                    issue_type="out_of_range",
                    severity="warning",
                    message=f"期待開始日より前の期間です: {entry.period_start.isoformat()}",
                    source_id=entry.source_id,
                    current_period_start=entry.period_start,
                    current_period_end=entry.period_end,
                )
            )
        if expected_end is not None and entry.period_end > expected_end:
            issues.append(
                ContinuityIssue(
                    issue_type="out_of_range",
                    severity="warning",
                    message=f"期待終了日より後の期間です: {entry.period_end.isoformat()}",
                    source_id=entry.source_id,
                    current_period_start=entry.period_start,
                    current_period_end=entry.period_end,
                )
            )

        if previous is None:
            previous = entry
            continue

        if entry.period_start == previous.period_start and entry.period_end == previous.period_end:
            previous = entry
            continue

        if entry.period_start <= previous.period_end:
            issues.append(
                ContinuityIssue(
                    issue_type="overlap",
                    severity="warning",
                    message=(
                        "期間が重複しています: "
                        f"{previous.period_start.isoformat()} - {previous.period_end.isoformat()} "
                        f"and {entry.period_start.isoformat()} - {entry.period_end.isoformat()}"
                    ),
                    source_id=entry.source_id,
                    previous_period_end=previous.period_end,
                    current_period_start=entry.period_start,
                    current_period_end=entry.period_end,
                )
            )
        elif entry.period_start > previous.period_end + timedelta(days=1):
            missing_start = previous.period_end + timedelta(days=1)
            missing_end = entry.period_start - timedelta(days=1)
            issues.append(
                ContinuityIssue(
                    issue_type="gap",
                    severity="warning",
                    message=(
                        "期間に欠落があります: "
                        f"{missing_start.isoformat()} -> {missing_end.isoformat()}"
                    ),
                    source_id=entry.source_id,
                    previous_period_end=previous.period_end,
                    current_period_start=missing_start,
                    current_period_end=missing_end,
                )
            )

        previous = entry

    last_entry = sorted_entries[-1]
    if expected_end is not None and last_entry.period_end < expected_end:
        missing_start = last_entry.period_end + timedelta(days=1)
        issues.append(
            ContinuityIssue(
                issue_type="gap",
                severity="warning",
                message=(
                    "最後の取得期間から期待終了日までに欠落があります: "
                    f"{missing_start.isoformat()} -> {expected_end.isoformat()}"
                ),
                source_id=last_entry.source_id,
                previous_period_end=last_entry.period_end,
                current_period_start=missing_start,
                current_period_end=expected_end,
            )
        )

    return issues
