from __future__ import annotations

from pathlib import Path

import pandas as pd

from .gui.style_tuner_window import launch_style_tuner as _launch_style_tuner_window
from .gui.types import StyleTunerInput


def launch_style_tuner(
    *,
    input_csv: Path | None,
    value_kind: str,
    title: str,
    sample_mode: str,
    profile_path: Path | None,
    preview_span: str,
    master=None,
    input_frame: pd.DataFrame | None = None,
    source_kind: str = "csv",
) -> None:
    tuner_input = (
        StyleTunerInput(
            source_kind=source_kind,
            frame=input_frame,
            value_kind=value_kind,
            preview_span=preview_span,
            title_template=title,
        )
        if input_frame is not None
        else None
    )
    _launch_style_tuner_window(
        tuner_input=tuner_input,
        input_csv=input_csv,
        value_kind=value_kind,
        title=title,
        sample_mode=sample_mode,
        profile_path=profile_path,
        preview_span=preview_span,
        master=master,
    )


__all__ = ["launch_style_tuner", "StyleTunerInput"]

