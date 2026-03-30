from __future__ import annotations

from pathlib import Path

from PIL import Image

from uc_rainfall_zipflow.gui.app import (
    A4MergeSpec,
    choose_a4_layout_plan,
    merge_pngs_to_a4,
)


def test_choose_layout_plan_uses_fixed_rows_columns() -> None:
    plan = choose_a4_layout_plan(
        image_sizes=[(1000, 700)] * 10,
        spec=A4MergeSpec(columns=2, rows=4),
    )

    assert plan.cols == 2
    assert plan.rows == 4
    assert plan.page_count == 2
    assert plan.cell_width_px == 1000
    assert plan.cell_height_px == 700


def test_choose_layout_plan_validates_rows_columns() -> None:
    try:
        choose_a4_layout_plan(image_sizes=[(100, 100)], spec=A4MergeSpec(columns=0, rows=4))
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    try:
        choose_a4_layout_plan(image_sizes=[(100, 100)], spec=A4MergeSpec(columns=2, rows=0))
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_merge_pngs_to_grid_outputs_files(tmp_path: Path) -> None:
    src_dir = tmp_path / "inputs"
    src_dir.mkdir(parents=True, exist_ok=True)
    input_paths: list[Path] = []
    for idx in range(9):
        path = src_dir / f"img_{idx:02d}.png"
        img = Image.new("RGB", (1000, 700), "white")
        img.save(path)
        input_paths.append(path)

    result = merge_pngs_to_a4(
        input_paths=input_paths,
        output_dir=tmp_path,
        spec=A4MergeSpec(columns=2, rows=4),
    )

    assert len(result.paths) == 2
    for out in result.paths:
        assert out.exists()
        assert out.name.startswith("merged_2x4_")
    assert result.warning is None
