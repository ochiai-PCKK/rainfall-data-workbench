from __future__ import annotations

import json

from uc_rainfall_zipflow.style_profile import load_style_profile


def test_load_style_profile_fills_x_axis_defaults(tmp_path) -> None:
    path = tmp_path / "style.json"
    path.write_text(json.dumps({"fig_width": 4.0}), encoding="utf-8")
    profile = load_style_profile(path)
    assert profile.x_tick_hours_list == [6, 12, 18]
    assert profile.x_date_label_format == "%Y.%m.%d"
    assert profile.x_margin_hours_left == 0.5
    assert profile.x_margin_hours_right == 0.5


def test_load_style_profile_coerces_x_tick_hours_list(tmp_path) -> None:
    path = tmp_path / "style.json"
    path.write_text(
        json.dumps(
            {
                "x_tick_hours_list": ["18", "6", "12", "6", "30", "-1", "bad"],
            }
        ),
        encoding="utf-8",
    )
    profile = load_style_profile(path)
    assert profile.x_tick_hours_list == [6, 12, 18]
