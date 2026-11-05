"""A narrow typed document model with explicit source witnesses."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from .discovery import RefinementError, repository_path


@dataclass(frozen=True)
class Entry:
    label: str
    href: str
    description: str
    evidence_path: str


@dataclass(frozen=True)
class Section:
    key: str
    title: str
    subtitle: str
    href: str | None
    entries: tuple[Entry, ...]


@dataclass(frozen=True)
class Document:
    snapshot_sha: str
    document_path: str
    title: str
    tagline: str
    introduction: str
    sections: tuple[Section, ...]
    closing: str


def _object(value: Any, allowed: set[str], context: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) - allowed:
        raise RefinementError(f"{context} must be an object with supported fields")
    return value


def _text(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 1500
        or any(ord(ch) < 32 and ch not in "\t" for ch in value)
    ):
        raise RefinementError(f"{field} must be nonempty single-line text")
    return value.strip()


def _array(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise RefinementError(f"{field} must be a nonempty list")
    return value


def build_document(payload: dict[str, Any], inventory: frozenset[str]) -> Document:
    """Construct and validate a document without inventing a claim."""
    root = _object(
        payload,
        {
            "snapshot_sha", "document_path", "title", "tagline",
            "introduction", "sections", "closing",
        },
        "payload",
    )
    doc_path = repository_path(root.get("document_path"))
    sections: list[Section] = []
    keys: set[str] = set()
    for idx, raw in enumerate(_array(root.get("sections"), "sections")):
        item = _object(raw, {"key", "title", "subtitle", "href", "entries"}, "section")
        key = _text(item.get("key"), f"sections[{idx}].key")
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", key) or key in keys:
            raise RefinementError("section keys must be unique slugs")
        keys.add(key)
        entries: list[Entry] = []
        for n, raw_entry in enumerate(_array(item.get("entries"), "entries")):
            data = _object(
                raw_entry, {"label", "href", "description", "evidence_path"}, "entry"
            )
            witness = repository_path(data.get("evidence_path"))
            if witness not in inventory:
                raise RefinementError(f"entry witness missing from inventory: {witness}")
            entries.append(
                Entry(
                    label=_text(data.get("label"), f"entry[{n}].label"),
                    href=_text(data.get("href"), f"entry[{n}].href"),
                    description=_text(data.get("description"), f"entry[{n}].description"),
                    evidence_path=witness,
                )
            )
        optional_href = item.get("href")
        sections.append(
            Section(
                key=key,
                title=_text(item.get("title"), "section.title"),
                subtitle=_text(item.get("subtitle"), "section.subtitle"),
                href=_text(optional_href, "section.href") if optional_href is not None else None,
                entries=tuple(entries),
            )
        )
    return Document(
        snapshot_sha=_text(root.get("snapshot_sha"), "snapshot_sha"),
        document_path=doc_path,
        title=_text(root.get("title"), "title"),
        tagline=_text(root.get("tagline"), "tagline"),
        introduction=_text(root.get("introduction"), "introduction"),
        sections=tuple(sections),
        closing=_text(root.get("closing"), "closing"),
    )
