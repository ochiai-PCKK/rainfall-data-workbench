from __future__ import annotations

import math
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class A4MergeSpec:
    columns: int
    rows: int


@dataclass(frozen=True)
class A4LayoutPlan:
    cols: int
    rows: int
    page_count: int
    cell_width_px: int
    cell_height_px: int
    canvas_width_px: int
    canvas_height_px: int


@dataclass(frozen=True)
class A4MergeResult:
    paths: list[Path]
    plan: A4LayoutPlan
    warning: str | None


def choose_a4_layout_plan(
    *,
    image_sizes: list[tuple[int, int]],
    spec: A4MergeSpec,
) -> A4LayoutPlan:
    if not image_sizes:
        raise ValueError("画像がありません。")
    if spec.columns <= 0 or spec.rows <= 0:
        raise ValueError("画像マージ設定が不正です。")

    base_cell_w = max(max(1, int(w)) for w, _ in image_sizes)
    base_cell_h = max(max(1, int(h)) for _, h in image_sizes)
    image_count = len(image_sizes)

    cols = int(spec.columns)
    rows = int(spec.rows)
    capacity = cols * rows
    page_count = int(math.ceil(image_count / capacity))
    return A4LayoutPlan(
        cols=cols,
        rows=rows,
        page_count=page_count,
        cell_width_px=base_cell_w,
        cell_height_px=base_cell_h,
        canvas_width_px=base_cell_w * cols,
        canvas_height_px=base_cell_h * rows,
    )


def merge_pngs_to_a4(
    *,
    input_paths: list[Path],
    output_dir: Path,
    spec: A4MergeSpec,
) -> A4MergeResult:
    png_paths = [path for path in input_paths if path.suffix.lower() == ".png" and path.exists()]
    if not png_paths:
        raise ValueError("マージ対象PNGがありません。")

    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("画像マージには Pillow が必要です。`uv add pillow` を実行してください。") from exc

    with ExitStack() as stack:
        images = [stack.enter_context(Image.open(path)) for path in png_paths]
        sizes = [(int(img.width), int(img.height)) for img in images]
    plan = choose_a4_layout_plan(image_sizes=sizes, spec=spec)

    merged_dir = output_dir / f"_merged_{plan.cols}x{plan.rows}"
    merged_dir.mkdir(parents=True, exist_ok=True)
    capacity = plan.cols * plan.rows
    merged_paths: list[Path] = []

    for page_index in range(plan.page_count):
        start = page_index * capacity
        chunk = png_paths[start : start + capacity]
        if not chunk:
            continue
        canvas = Image.new("RGB", (plan.canvas_width_px, plan.canvas_height_px), "white")
        with ExitStack() as stack:
            page_images = [stack.enter_context(Image.open(path)) for path in chunk]
            for pos, img in enumerate(page_images):
                row = pos // plan.cols
                col = pos % plan.cols
                cell_x = col * plan.cell_width_px
                cell_y = row * plan.cell_height_px
                resized = img.convert("RGB")
                paste_x = cell_x + max(0, (plan.cell_width_px - resized.width) // 2)
                paste_y = cell_y + max(0, (plan.cell_height_px - resized.height) // 2)
                canvas.paste(resized, (paste_x, paste_y))
        out_path = merged_dir / f"merged_{plan.cols}x{plan.rows}_{page_index + 1:03d}.png"
        canvas.save(out_path)
        merged_paths.append(out_path)
    return A4MergeResult(paths=merged_paths, plan=plan, warning=None)
