from __future__ import annotations

from pathlib import Path

import pytest

from uc_rainfall_zipflow import cli
def test_run_command_accepts_rust_pyo3_engine() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "run",
            "--base-date",
            "2024-01-03",
            "--engine",
            "rust_pyo3",
        ]
    )
    assert args.engine == "rust_pyo3"


def test_run_command_rejects_unknown_engine() -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "run",
                "--base-date",
                "2024-01-03",
                "--engine",
                "rust",
            ]
        )


def test_benchmark_parser_defaults() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["benchmark"])
    assert args.repeat == 3
    assert args.warmup == 1
    assert args.slots == 120
    assert args.rebuild_rust is False
    assert args.use_pyo3 is False
    assert args.rebuild_pyo3 is False
    assert Path(args.rust_manifest).as_posix().endswith("rust/weighted_core/Cargo.toml")
    assert Path(args.pyo3_manifest).as_posix().endswith("rust/weighted_core_pyo3/Cargo.toml")
