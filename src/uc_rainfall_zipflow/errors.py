from __future__ import annotations


class ZipFlowError(RuntimeError):
    """終了コード付きの実行例外。"""

    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code
