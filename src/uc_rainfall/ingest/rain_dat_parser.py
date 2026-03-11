from __future__ import annotations

import re
from pathlib import Path

HEADER_RE = re.compile(r"^\d+\s+\d+\s+\d+$")


def parse_rain_dat(path: str | Path) -> tuple[list[int], list[list[list[float]]], int, int]:
    """`rain.dat` を時間ブロック単位で読み取り、格子行列へ展開する。"""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    headers = [index for index, line in enumerate(lines) if HEADER_RE.fullmatch(line.strip())]
    if not headers:
        raise ValueError(f"rain.dat のブロックヘッダが見つかりません: {path}")

    elapsed_seconds: list[int] = []
    matrices: list[list[list[float]]] = []
    resolved_rows: int | None = None
    resolved_cols: int | None = None

    for index, start in enumerate(headers):
        end = headers[index + 1] if index + 1 < len(headers) else len(lines)
        elapsed_str, dim_a_str, dim_b_str = lines[start].split()
        elapsed = int(elapsed_str)
        dim_a = int(dim_a_str)
        dim_b = int(dim_b_str)

        matrix = [[float(token) for token in line.split()] for line in lines[start + 1 : end] if line.strip()]
        if not matrix:
            raise ValueError(f"空のデータブロックがあります: elapsed={elapsed}")

        parsed_line_count = len(matrix)
        parsed_token_count = len(matrix[0])
        if any(len(row) != parsed_token_count for row in matrix):
            raise ValueError(f"ブロック内の列数が一致しません: elapsed={elapsed}")

        if dim_a == parsed_token_count and dim_b == parsed_line_count:
            cols, rows = dim_a, dim_b
        elif dim_a == parsed_line_count and dim_b == parsed_token_count:
            rows, cols = dim_a, dim_b
        else:
            raise ValueError(
                f"ヘッダ寸法とブロック寸法が一致しません: elapsed={elapsed} "
                f"header=({dim_a},{dim_b}) parsed=({parsed_line_count},{parsed_token_count})"
            )

        if resolved_rows is None:
            resolved_rows, resolved_cols = rows, cols
        elif (rows, cols) != (resolved_rows, resolved_cols):
            raise ValueError(f"格子サイズが途中で変化しています: {(rows, cols)} != {(resolved_rows, resolved_cols)}")

        elapsed_seconds.append(elapsed)
        matrices.append(matrix)

    if resolved_rows is None or resolved_cols is None:
        raise ValueError(f"rain.dat の格子サイズを決定できません: {path}")
    return elapsed_seconds, matrices, resolved_rows, resolved_cols
