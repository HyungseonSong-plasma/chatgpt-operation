"""Validate Python-bearing repository surfaces before integration tests."""
from __future__ import annotations

import ast
from pathlib import Path


def workflow_run_scripts(text: str) -> list[str]:
    """Extract YAML run-block scalar bodies using YAML indentation semantics."""
    lines = text.splitlines()
    scripts: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.lstrip()
        if stripped not in {"run: |", "- run: |"}:
            index += 1
            continue
        run_indent = len(line) - len(stripped)
        index += 1
        probe = index
        while probe < len(lines) and not lines[probe].strip():
            probe += 1
        if probe >= len(lines):
            scripts.append("")
            continue
        body_indent = len(lines[probe]) - len(lines[probe].lstrip())
        if body_indent <= run_indent:
            scripts.append("")
            continue
        body: list[str] = []
        while index < len(lines):
            current = lines[index]
            if current.strip():
                current_indent = len(current) - len(current.lstrip())
                if current_indent < body_indent:
                    break
                body.append(current[body_indent:])
            else:
                body.append("")
            index += 1
        scripts.append("\n".join(body))
    return scripts


def embedded_python_blocks(script: str) -> list[str]:
    """Extract shell heredocs introduced by python3 with a PY terminator."""
    lines = script.splitlines()
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        if "python3 - <<'PY'" not in lines[index]:
            index += 1
            continue
        index += 1
        body: list[str] = []
        while index < len(lines) and lines[index] != "PY":
            body.append(lines[index])
            index += 1
        if index >= len(lines):
            raise ValueError("unterminated python3 heredoc")
        blocks.append("\n".join(body))
        index += 1
    return blocks


def validate_workflow_text(text: str, *, filename: str) -> list[str]:
    failures: list[str] = []
    for script_number, script in enumerate(workflow_run_scripts(text), 1):
        try:
            blocks = embedded_python_blocks(script)
        except ValueError as exc:
            failures.append(f"{filename}:run-{script_number}: {exc}")
            continue
        for block_number, source in enumerate(blocks, 1):
            try:
                ast.parse(
                    source,
                    filename=f"{filename}:run-{script_number}:embedded-python-{block_number}",
                )
            except SyntaxError as exc:
                failures.append(str(exc))
    return failures


def main() -> None:
    failures: list[str] = []
    for path in Path(".github/workflows").glob("*.yml"):
        failures.extend(validate_workflow_text(
            path.read_text(encoding="utf-8"),
            filename=str(path),
        ))
    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
