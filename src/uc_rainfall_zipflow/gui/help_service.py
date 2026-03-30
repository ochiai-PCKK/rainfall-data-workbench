from __future__ import annotations

import sys
from pathlib import Path

from ..runtime_paths import resolve_path

GUI_HELP_REL_PATH = Path("config") / "uc_rainfall_zipflow" / "gui_help.txt"

DEFAULT_GUI_HELP_TEXT = """【流域雨量グラフ作成 ヘルプ】

1. モード
- 解析雨量データ: ZIP入力から流域ごとの出力を作成します。
- Excelデータ: Excelシート時系列から整形グラフを作成します。

2. 基本操作
- 入出力欄で入力元と出力先を指定します。
- 実行設定で対象流域・出力種別・グラフ指標を選びます。
- 「処理を実行」で出力を開始します。

3. 画像マージ
- 「実行後に画像マージ」をONにすると、実行完了後に自動でマージします。
- 「今すぐ画像マージ」で、既存の plots_reference PNG を対象に手動実行できます。
- 行列は「列数」「行数」で指定します（初期値: 2列 x 4行）。
- 最後のページに余りがある場合は空欄のまま出力します。

4. グラフスタイル調整
- 「グラフスタイル調整」で見た目を変更できます。
- 保存して閉じると、次回実行から反映されます。

5. よくあるエラー
- 入力ファイルが見つからない:
  パスを再確認し、読み取り可能な場所を指定してください。
- Excel期間不一致:
  シート名日付と時刻列(B列)の期間整合を確認してください。
- 画像マージ対象なし:
  先に plots_reference のPNGを出力してください。
"""


def _load_gui_help_text(path: Path) -> str:
    if not path.exists():
        return (
            "ヘルプファイルが見つかりません。\n\n"
            f"対象: {path}\n"
            "管理者に連絡してヘルプファイルを配置してください。"
        )
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return (
            "ヘルプファイルの読み込みに失敗しました。\n\n"
            f"対象: {path}\n"
            f"詳細: {exc}"
        )
    stripped = text.strip()
    if not stripped:
        return (
            "ヘルプファイルが空です。\n\n"
            f"対象: {path}\n"
            "ヘルプ内容を記述してください。"
        )
    return stripped


def _preferred_gui_help_output_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / GUI_HELP_REL_PATH
    return resolve_path(*GUI_HELP_REL_PATH.parts)


def _ensure_gui_help_file_exists() -> Path | None:
    target = _preferred_gui_help_output_path()
    if target.exists():
        return target
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(DEFAULT_GUI_HELP_TEXT.strip() + "\n", encoding="utf-8")
        return target
    except Exception:
        return None


def _iter_gui_help_candidates() -> list[Path]:
    exe_dir = Path(sys.executable).resolve().parent
    return [
        exe_dir / GUI_HELP_REL_PATH,
        exe_dir / "gui_help.txt",
        resolve_path(*GUI_HELP_REL_PATH.parts),
    ]


def _load_gui_help_text_from_candidates() -> str:
    auto_generated = _ensure_gui_help_file_exists()
    if auto_generated is not None and auto_generated.exists():
        return _load_gui_help_text(auto_generated)
    candidates = _iter_gui_help_candidates()
    for path in candidates:
        if path.exists():
            return _load_gui_help_text(path)
    return DEFAULT_GUI_HELP_TEXT.strip()
