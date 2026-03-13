from __future__ import annotations

import logging
from collections.abc import Callable


class GuiLogHandler(logging.Handler):
    """logging を GUI のログ欄へ流すハンドラ。"""

    def __init__(self, append_callback: Callable[[str], None]) -> None:
        super().__init__(level=logging.INFO)
        self._append_callback = append_callback
        self.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        """ログレコードを GUI 側へ追記する。"""
        try:
            message = self.format(record)
        except Exception:
            self.handleError(record)
            return
        self._append_callback(message)
