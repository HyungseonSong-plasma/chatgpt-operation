"""Conservative Markdown and repository-link preservation checks.

This is not a full GFM parser, semantic verifier or live URL checker.
"""

from __future__ import annotations

from collections import Counter
import posixpath
import re
from urllib.parse import urlsplit

from .discovery import RefinementError
from .structure import Document


_MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]\n]+\]\(([^)\s]+)\)")
_HTML_LINK = re.compile(r"""<a\s+[^>]*href=["']([^"']+)["']""", re.I)


def extract_links(markdown: str) -> list[str]:
    """Extract Markdown targets and simple HTML anchor hrefs."""
    if not isinstance(markdown, str):
        raise RefinementError("Markdown must be text")
    return _MARKDOWN_LINK.findall(markdown) + _HTML_LINK.findall(markdown)


def _validate_target(href: str, document_path: str, inventory: frozenset[str]) -> None:
    if not isinstance(href, str) or not href or re.search(r"[\s<>'\"\\]", href):
        raise RefinementError(f"invalid link target: {href!r}")
    parts = urlsplit(href)
    if parts.scheme or parts.netloc:
        if parts.scheme != "https" or not parts.netloc or not href.startswith("https://"):
            raise RefinementError(f"unsafe external link: {href}")
        return
    if href.startswith("/") or parts.query:
        raise RefinementError(f"unsupported repository link: {href}")
    if not parts.path:  # Same-document fragment.
        if not parts.fragment:
            raise RefinementError(f"empty repository link: {href}")
        return
    joined = posixpath.normpath(
        posixpath.join(posixpath.dirname(document_path), parts.path)
    )
    if joined in {".", ".."} or joined.startswith("../"):
        raise RefinementError(f"link escapes repository: {href}")
    if parts.path.endswith("/"):
        exists = any(path.startswith(joined.rstrip("/") + "/") for path in inventory)
    else:
        exists = joined in inventory
    if not exists:
        raise RefinementError(f"link has no source-inventory target: {href}")


def validate_rendered(
    *,
    document: Document,
    markdown: str,
    inventory: frozenset[str],
    baseline_markdown: str,
    required_claims: list[str],
) -> tuple[int, int]:
    """Check supported links and required phrases, never infer meaning."""
    if not isinstance(required_claims, list) or any(
        not isinstance(claim, str) or not claim.strip() for claim in required_claims
    ):
        raise RefinementError("required_claims must be a list of nonempty strings")

    baseline_links = extract_links(baseline_markdown)
    candidate_links = extract_links(markdown)
    missing = Counter(baseline_links) - Counter(candidate_links)
    if missing:
        raise RefinementError(f"baseline links removed: {sorted(missing.elements())}")

    for href in candidate_links:
        _validate_target(href, document.document_path, inventory)

    baseline_flat = " ".join(baseline_markdown.split())
    candidate_flat = " ".join(markdown.split())
    for claim in required_claims:
        expected = " ".join(claim.split())
        if expected not in baseline_flat or expected not in candidate_flat:
            raise RefinementError(f"required claim not preserved: {claim}")

    return len(baseline_links), len(required_claims)
