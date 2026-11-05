"""Conservative whitespace compaction: never drop links, entries or claims."""

from __future__ import annotations

from dataclasses import replace

from .structure import Document


def _compact(value: str) -> str:
    return " ".join(value.split())


def compact_document(document: Document) -> Document:
    """Normalize presentation whitespace without changing data membership."""
    sections = tuple(
        replace(
            section,
            title=_compact(section.title),
            subtitle=_compact(section.subtitle),
            entries=tuple(
                replace(
                    entry,
                    label=_compact(entry.label),
                    description=_compact(entry.description),
                )
                for entry in section.entries
            ),
        )
        for section in document.sections
    )
    return replace(
        document,
        title=_compact(document.title),
        tagline=_compact(document.tagline),
        introduction=_compact(document.introduction),
        closing=_compact(document.closing),
        sections=sections,
    )
