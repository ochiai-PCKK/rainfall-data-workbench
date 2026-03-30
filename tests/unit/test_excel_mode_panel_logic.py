from __future__ import annotations

from datetime import date
from pathlib import Path

from uc_rainfall_zipflow.gui.excel_mode_panel import ExcelCandidateSelection, ExcelModePanel


def _candidate(
    *,
    key: str,
    event_date: date,
    is_resplit: bool,
    source_index: int = 1,
) -> ExcelCandidateSelection:
    return ExcelCandidateSelection(
        event_key=key,
        source_path=Path("dummy.xlsx"),
        source_alias="dummy.xlsx",
        source_index=source_index,
        event_date=event_date,
        sheet_name="dummy",
        is_resplit=is_resplit,
    )


def test_preferred_keys_by_date_selects_resplit_only_when_exists() -> None:
    candidates = [
        _candidate(key="a", event_date=date(2026, 3, 1), is_resplit=False),
        _candidate(key="b", event_date=date(2026, 3, 1), is_resplit=True),
        _candidate(key="c", event_date=date(2026, 3, 2), is_resplit=False),
        _candidate(key="d", event_date=date(2026, 3, 2), is_resplit=False),
    ]

    selected, resplit_days, normal_days = ExcelModePanel._preferred_keys_by_date(candidates)

    assert "b" in selected
    assert "a" not in selected
    assert "c" in selected
    assert "d" in selected
    assert resplit_days == 1
    assert normal_days == 1
