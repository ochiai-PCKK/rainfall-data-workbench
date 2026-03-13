from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _json_default(value: Any) -> Any:
    """JSON 保存時の補助変換を行う。"""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    """指定 JSON を UTF-8 で保存する。"""
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    return path


def _read_json(path: Path) -> dict[str, Any] | None:
    """存在する JSON を辞書として読み込む。"""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def get_gui_context_path() -> Path:
    """GUI 状態スナップショットの保存先を返す。"""
    return _PROJECT_ROOT / ".uc_rainfall_gui_context.json"


def get_widget_tree_path() -> Path:
    """ウィジェット一覧の保存先を返す。"""
    return _PROJECT_ROOT / ".uc_rainfall_gui_widget_tree.json"


def get_action_request_path() -> Path:
    """AI テストモードの操作要求ファイル保存先を返す。"""
    return _PROJECT_ROOT / ".uc_rainfall_gui_action_request.json"


def get_action_result_path() -> Path:
    """AI テストモードの操作結果ファイル保存先を返す。"""
    return _PROJECT_ROOT / ".uc_rainfall_gui_action_result.json"


def get_last_run_path() -> Path:
    """直近実行結果サマリの保存先を返す。"""
    return _PROJECT_ROOT / ".uc_rainfall_gui_last_run.json"


def get_gui_log_path() -> Path:
    """GUI ログ保存先を返す。"""
    return _PROJECT_ROOT / ".uc_rainfall_gui_log.txt"


def get_last_screenshot_path() -> Path:
    """直近スクリーンショット保存先を返す。"""
    return _PROJECT_ROOT / ".uc_rainfall_gui_last_screenshot.png"


def save_gui_context(payload: Mapping[str, Any]) -> Path:
    """GUI 状態スナップショットを保存する。"""
    return _write_json(get_gui_context_path(), payload)


def save_widget_tree(payload: Mapping[str, Any]) -> Path:
    """ウィジェット一覧スナップショットを保存する。"""
    return _write_json(get_widget_tree_path(), payload)


def load_action_request() -> dict[str, Any] | None:
    """AI テストモードの操作要求を読み込む。"""
    return _read_json(get_action_request_path())


def clear_action_request() -> None:
    """処理済み操作要求ファイルを削除する。"""
    path = get_action_request_path()
    if path.exists():
        path.unlink()


def save_action_result(payload: Mapping[str, Any]) -> Path:
    """操作結果を保存する。"""
    return _write_json(get_action_result_path(), payload)


def save_last_run(payload: Mapping[str, Any]) -> Path:
    """直近処理サマリを保存する。"""
    return _write_json(get_last_run_path(), payload)


def save_gui_log(lines: list[str]) -> Path:
    """GUI ログをテキストとして保存する。"""
    path = get_gui_log_path()
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
