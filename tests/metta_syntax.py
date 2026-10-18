"""Bracket balance for .metta files (strings and ; comments are skipped).

MeTTa reports an unbalanced file as a parse error far from the cause; this
points at the top-level form where the balance goes wrong.
"""
from __future__ import annotations

from pathlib import Path


def top_level_forms(text: str) -> list[tuple[int, int]]:
    """(start_line, end_line) for each top-level form; raises on imbalance."""
    forms: list[tuple[int, int]] = []
    depth = 0
    line = 1
    start = 0
    in_string = False
    in_comment = False
    escaped = False
    for ch in text:
        if ch == "\n":
            line += 1
            in_comment = False
            continue
        if in_comment:
            continue
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == ";":
            in_comment = True
        elif ch == '"':
            in_string = True
        elif ch == "(":
            if depth == 0:
                start = line
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                raise SyntaxError(f"line {line}: ')' with no matching '('")
            if depth == 0:
                forms.append((start, line))
    if depth != 0:
        raise SyntaxError(f"form starting on line {start} is never closed")
    return forms


def check_file(path: Path) -> list[tuple[int, int]]:
    return top_level_forms(path.read_text(encoding="utf-8"))
