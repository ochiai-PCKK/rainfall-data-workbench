from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class StyleTunerInput:
    source_kind: str  # excel | csv | template
    frame: pd.DataFrame | None
    value_kind: str  # sum | mean
    preview_span: str  # 3d | 5d
    title_template: str

