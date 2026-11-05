"""Versioned, read-only Markdown preservation and readability audit v0.2."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math

from .anchors import heading_anchors
from .discovery import RefinementError
from .validation import extract_links


@dataclass(frozen=True)
class ReadabilityBudget:
    """Consumer-selected limits; stricter/looser budgets require review.

    For small initial documents, catalog expansion may legitimately exceed
    default growth budgets. An override is a review decision, not a PASS.
    """
    max_character_growth_ratio: float = 1.8
    max_line_growth_ratio: float = 1.8
    max_table_row_chars: int = 240


@dataclass(frozen=True)
class ReadmeAudit:
    """Machine signals, not a claim of semantic or rendered-GFM equivalence."""

    issues: tuple[str, ...]
    missing_anchors: tuple[str, ...]
    missing_link_targets: tuple[str, ...]
    baseline_anchor_count: int
    candidate_anchor_count: int
    baseline_link_count: int
    candidate_link_count: int
    baseline_characters: int
    candidate_characters: int
    baseline_lines: int
    candidate_lines: int
    longest_table_row: int

    @property
    def passed(self) -> bool:
        return not self.issues


def _check_budget(budget: ReadabilityBudget) -> None:
    if not isinstance(budget, ReadabilityBudget):
        raise RefinementError("budget must be ReadabilityBudget")
    for number in (budget.max_character_growth_ratio, budget.max_line_growth_ratio):
        if (
            isinstance(number, bool)
            or not isinstance(number, (float, int))
            or not math.isfinite(number)
            or number < 1.0
        ):
            raise RefinementError("growth ratio must be finite and >= 1")
    if (
        isinstance(budget.max_table_row_chars, bool)
        or not isinstance(budget.max_table_row_chars, int)
        or budget.max_table_row_chars < 40
    ):
        raise RefinementError("max_table_row_chars must be an integer >= 40")


def _table_rows(markdown: str) -> list[int]:
    """Count table rows outside fenced code blocks."""
    from .anchors import _FENCE  # Reuse the conservative fence recognition.

    rows: list[int] = []
    active: tuple[str, int] | None = None
    for line in markdown.splitlines():
        fence = _FENCE.match(line)
        if fence:
            delimiter = fence.group("marker")
            if active is None:
                active = (delimiter[0], len(delimiter))
                continue
            if delimiter[0] == active[0] and len(delimiter) >= active[1]:
                active = None
                continue
        if active is None and line.lstrip().startswith("|"):
            rows.append(len(line))
    return rows


def audit_markdown_v02(
    baseline_markdown: str,
    candidate_markdown: str,
    *,
    budget: ReadabilityBudget | None = None,
) -> ReadmeAudit:
    """Audit baseline links, legacy heading anchors and readability budgets.

    Explicit aliases may preserve old anchors; a raw <h1> is not counted as
    an auto-generated anchor. Subset parsing is conservative and consumers
    must review actual GitHub rendering before relying on anchor behavior.
    """
    if not isinstance(baseline_markdown, str) or not baseline_markdown.strip():
        raise RefinementError("baseline_markdown must be nonempty")
    if not isinstance(candidate_markdown, str) or not candidate_markdown.strip():
        raise RefinementError("candidate_markdown must be nonempty")

    rule = budget or ReadabilityBudget()
    _check_budget(rule)

    old_links = extract_links(baseline_markdown)
    new_links = extract_links(candidate_markdown)
    missing_links = Counter(old_links) - Counter(new_links)
    missing_targets = tuple(sorted(missing_links.elements()))

    old_anchors = heading_anchors(baseline_markdown)
    new_anchors = heading_anchors(candidate_markdown)
    missing_anchors = tuple(sorted(old_anchors - new_anchors))

    internal_broken = tuple(sorted({
        href for href in new_links
        if href.startswith("#") and href[1:] not in new_anchors
    }))

    old_lines = len(baseline_markdown.splitlines())
    new_lines = len(candidate_markdown.splitlines())
    longest_table = max(_table_rows(candidate_markdown), default=0)

    issues: list[str] = []
    if missing_targets:
        issues.append("LINK_TARGET_REMOVED")
    if missing_anchors:
        issues.append("LEGACY_ANCHOR_REMOVED")
    if internal_broken:
        issues.append("LOCAL_FRAGMENT_UNRESOLVED")
    if len(candidate_markdown) > len(baseline_markdown) * rule.max_character_growth_ratio:
        issues.append("CHARACTER_BUDGET_EXCEEDED")
    if new_lines > old_lines * rule.max_line_growth_ratio:
        issues.append("LINE_BUDGET_EXCEEDED")
    if longest_table > rule.max_table_row_chars:
        issues.append("TABLE_ROW_TOO_WIDE")

    return ReadmeAudit(
        issues=tuple(issues),
        missing_anchors=missing_anchors,
        missing_link_targets=missing_targets,
        baseline_anchor_count=len(old_anchors),
        candidate_anchor_count=len(new_anchors),
        baseline_link_count=len(old_links),
        candidate_link_count=len(new_links),
        baseline_characters=len(baseline_markdown),
        candidate_characters=len(candidate_markdown),
        baseline_lines=old_lines,
        candidate_lines=new_lines,
        longest_table_row=longest_table,
    )


def enforce_markdown_v02(
    baseline_markdown: str,
    candidate_markdown: str,
    *,
    budget: ReadabilityBudget | None = None,
) -> ReadmeAudit:
    """Fail closed on any audit issue. No repository mutation is performed."""
    result = audit_markdown_v02(
        baseline_markdown, candidate_markdown, budget=budget
    )
    if not result.passed:
        raise RefinementError("documentation v0.2 audit failed: " + ", ".join(result.issues))
    return result
