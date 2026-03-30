from __future__ import annotations

from typing import Any


def format_summary(result: dict[str, object]) -> str:
    if result.get("event_count") is not None:
        lines = [
            f"出力先: {result.get('base_dir')}",
            f"対象イベント数: {result.get('event_count')}",
            f"グラフ出力数: {result.get('plot_count')}",
        ]
        if result.get("log_path"):
            lines.append(f"ログ: {result['log_path']}")
        if result.get("intermediate_json_path"):
            lines.append(f"中間JSON: {result['intermediate_json_path']}")
        if result.get("merged_a4_count") is not None:
            lines.append(
                "画像マージ: "
                f"{result.get('merged_a4_count')}ページ "
                f"(layout={result.get('merged_a4_layout')})"
            )
            if result.get("merged_a4_warning"):
                lines.append(f"警告: {result.get('merged_a4_warning')}")
        return "\n".join(lines)
    lines = [
        f"出力先: {result.get('base_dir')}",
        f"採用ZIP数: {result.get('zip_count')}",
        f"グラフ出力数: {result.get('plot_count')}",
        f"時系列CSV数: {result.get('csv_count')} / セルCSV数: {result.get('cell_csv_count')}",
    ]
    if result.get("log_path"):
        lines.append(f"ログ: {result['log_path']}")
    if result.get("csv_readme_path"):
        lines.append(f"CSV説明: {result['csv_readme_path']}")
    if result.get("merged_a4_count") is not None:
        lines.append(
            "画像マージ: "
            f"{result.get('merged_a4_count')}ページ "
            f"(layout={result.get('merged_a4_layout')})"
        )
        if result.get("merged_a4_warning"):
            lines.append(f"警告: {result.get('merged_a4_warning')}")
    return "\n".join(lines)


def build_completion_message(result: dict[str, object], *, mode: str) -> str:
    if mode == "Excelデータ":
        lines = [
            "処理が完了しました。",
            f"対象イベント数: {result.get('event_count')}",
            f"グラフ出力数: {result.get('plot_count')}",
            f"出力先: {result.get('base_dir')}",
        ]
        if result.get("log_path"):
            lines.append(f"ログ: {result.get('log_path')}")
        if result.get("intermediate_json_path"):
            lines.append(f"中間JSON: {result.get('intermediate_json_path')}")
        if result.get("merged_a4_count") is not None:
            lines.append(
                "画像マージ: "
                f"{result.get('merged_a4_count')}ページ "
                f"(layout={result.get('merged_a4_layout')})"
            )
            if result.get("merged_a4_warning"):
                lines.append(f"警告: {result.get('merged_a4_warning')}")
        return "\n".join(lines)
    lines = [
        "処理が完了しました。",
        f"採用ZIP数: {result.get('zip_count')}",
        f"グラフ出力数: {result.get('plot_count')}",
        f"時系列CSV数: {result.get('csv_count')}",
        f"セルCSV数: {result.get('cell_csv_count')}",
        f"出力先: {result.get('base_dir')}",
    ]
    if result.get("log_path"):
        lines.append(f"ログ: {result.get('log_path')}")
    if result.get("merged_a4_count") is not None:
        lines.append(
            "画像マージ: "
            f"{result.get('merged_a4_count')}ページ "
            f"(layout={result.get('merged_a4_layout')})"
        )
        if result.get("merged_a4_warning"):
            lines.append(f"警告: {result.get('merged_a4_warning')}")
    return "\n".join(lines)
