from __future__ import annotations

import logging
from pathlib import Path


def build_logger(*, enable_file: bool, log_path: Path | None) -> logging.Logger:
    """ZIP Flow 用ロガーを構築する。"""
    logger = logging.getLogger("uc_rainfall_zipflow")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter("[%(levelname)s] %(message)s")
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.addHandler(stream)

    if enable_file and log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    return logger
