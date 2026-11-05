"""Conservative GitHub-style Markdown heading anchor inventory.

Only explicit Markdown headings and deliberate <a id/name="..."> anchors count
as reliable anchors. Raw HTML heading tags are *not* assumed to receive
GitHub's generated IDs. This is deliberately a subset of GitHub Markdown.
"""

from __future__ import annotations

from collections import defaultdict
from html import unescape
import re


_FENCE = re.compile(r"^ {0,3}(?P<marker>\x60{3,}|~{3,})(?:[^\r\n]*)$")
_ATX = re.compile(r"^ {0,3}#{1,6}(?:[ \t]+|$)(.*)$")
_SETEXT = re.compile(r"^ {0,3}(?:=+|-+)[ \t]*$")
_EXPLICIT = re.compile(
    r"""<a\b[^>]*\b(?:id|name)\s*=\s*["']([^"']+)["'][^>]*>""", re.I
)
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_TAG = re.compile(r"<[^>]+>")
_INLINE_CODE = re.compile(r"\x60+([^\x60]+)\x60+")


def _visible_heading_text(raw: str) -> str:
    value = re.sub(r"[ \t]+#+[ \t]*$", "", raw.strip())
    value = _IMAGE.sub(r"\1", value)
    value = _LINK.sub(r"\1", value)
    value = _INLINE_CODE.sub(r"\1", value)
    value = _TAG.sub("", value)
    value = unescape(value).lower()
    return "".join(
        ch for ch in value
        if ch.isalnum() or ch in {"-", "_", " "}
    ).replace(" ", "-")


def heading_anchors(markdown: str) -> frozenset[str]:
    """Extract stable anchor IDs from supported Markdown features.

    Duplicate headings use -1/-2 suffixes, matching ordinary GitHub heading
    links. Contents of fenced code blocks are never interpreted as headings.
    Explicit <a id/name> references are included only when well formed.
    """
    if not isinstance(markdown, str):
        raise TypeError("markdown must be a string")
    visible_lines: list[str | None] = []
    active: tuple[str, int] | None = None
    explicit: set[str] = set()

    for line in markdown.splitlines():
        fence = _FENCE.match(line)
        if fence is not None:
            chars = fence.group("marker")
            if active is None:
                active = (chars[0], len(chars))
                visible_lines.append(None)
                continue
            if chars[0] == active[0] and len(chars) >= active[1]:
                active = None
                visible_lines.append(None)
                continue
        if active is not None:
            visible_lines.append(None)
            continue
        visible_lines.append(line)
        for identifier in _EXPLICIT.findall(line):
            if re.fullmatch(r"[A-Za-z0-9_-]+", identifier):
                explicit.add(identifier)

    seen: defaultdict[str, int] = defaultdict(int)
    anchors: set[str] = set(explicit)
    previous: str | None = None
    for line in visible_lines:
        if line is None:
            previous = None
            continue
        atx = _ATX.match(line)
        text: str | None = atx.group(1) if atx is not None else None
        if text is None and _SETEXT.fullmatch(line) and previous:
            text = previous
        if text is not None:
            base = _visible_heading_text(text)
            if base:
                index = seen[base]
                anchors.add(base if index == 0 else f"{base}-{index}")
                seen[base] += 1
        previous = line if line.strip() and atx is None else None

    return frozenset(anchors)
