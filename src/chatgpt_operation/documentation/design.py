"""GitHub-compatible Markdown renderers for typed documentation."""

from __future__ import annotations

from html import escape as escape_html

from .discovery import RefinementError
from .structure import Document
from .validation import _validate_target


PRESETS = ("minimal", "fastapi-astro")


def _cell(value: str) -> str:
    """Escape special table/Markdown delimiters in literal model text."""
    return (
        value.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace(chr(96), "\\" + chr(96))
    )


def _section_heading(title: str, href: str | None) -> str:
    label = _cell(title)
    return f"[{label}]({href})" if href else label


def render_markdown(
    document: Document,
    *,
    preset: str,
    inventory: frozenset[str],
) -> str:
    """Render one candidate. All links are checked before interpolation."""
    if preset not in PRESETS:
        raise RefinementError(f"unknown design preset: {preset}")
    for section in document.sections:
        if section.href:
            _validate_target(section.href, document.document_path, inventory)
        for entry in section.entries:
            _validate_target(entry.href, document.document_path, inventory)

    if preset == "fastapi-astro":
        lines = [
            '<div align="center">',
            "",
            f"<h1>{escape_html(document.title)}</h1>",
            "",
            f"<p><strong>{escape_html(document.tagline)}</strong></p>",
            "",
            "</div>",
            "",
            "---",
            "",
            _cell(document.introduction),
            "",
            "## Contract Catalog",
            "",
        ]
    else:
        lines = [
            f"# {_cell(document.title)}",
            "",
            f"> **{_cell(document.tagline)}**",
            "",
            _cell(document.introduction),
            "",
        ]

    for index, section in enumerate(document.sections, 1):
        heading = _section_heading(section.title, section.href)
        prefix = f"{index:02d} · " if preset == "fastapi-astro" else ""
        lines.extend([
            f"### {prefix}{heading} — {_cell(section.subtitle)}",
            "",
            "| Contract | Purpose |",
            "| :-- | :-- |",
        ])
        for entry in section.entries:
            lines.append(
                f"| [{_cell(entry.label)}]({entry.href}) | {_cell(entry.description)} |"
            )
        lines.append("")

    lines.extend(["---", "", _cell(document.closing), ""])
    return "\n".join(lines)
