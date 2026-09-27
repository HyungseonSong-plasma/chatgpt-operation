"""Validate Python-bearing repository surfaces before integration tests."""
from __future__ import annotations

import ast
from pathlib import Path
import re


def embedded_python_blocks(text: str) -> list[str]:
    lines = text.splitlines()
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if "python3 - <<'PY'" not in line:
            index += 1
            continue
        indent = len(line) - len(line.lstrip())
        index += 1
        body: list[str] = []
        while index < len(lines):
            current = lines[index]
            if current.strip() == "PY" and len(current) - len(current.lstrip()) == indent:
                break
            body.append(current[indent:] if current.startswith(" " * indent) else current)
            index += 1
        nonblank = [line for line in body if line.strip()]
        body_indent = min(
            (len(line) - len(line.lstrip()) for line in nonblank),
            default=0,
        )
        blocks.append("\n".join(
            line[body_indent:] if line.strip() else ""
            for line in body
        ))
        index += 1
    return blocks


def main() -> None:
    failures: list[str] = []
    for path in Path(".github/workflows").glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        for number, source in enumerate(embedded_python_blocks(text), 1):
            try:
                ast.parse(source, filename=f"{path}:embedded-python-{number}")
            except SyntaxError as exc:
                failures.append(str(exc))
    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
