from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .application import run_zipflow as run_zipflow

__all__ = ["run_zipflow"]


def __getattr__(name: str):
    if name == "run_zipflow":
        from .application import run_zipflow

        return run_zipflow
    raise AttributeError(name)
