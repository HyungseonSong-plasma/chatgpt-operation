"""Regression checks for documentation-refinement v0.2 preservation gates."""

from __future__ import annotations

import unittest

from chatgpt_operation.documentation import (
    ReadabilityBudget,
    RefinementError,
    audit_markdown_v02,
    enforce_markdown_v02,
    heading_anchors,
)


LENIENT = ReadabilityBudget(
    max_character_growth_ratio=50.0,
    max_line_growth_ratio=50.0,
    max_table_row_chars=5000,
)


class DocumentationAuditV02Tests(unittest.TestCase):
    def test_legacy_h1_anchor_lost_when_replaced_with_html(self):
        source = "# CodeQA\n\n## Scope boundary\n\nThe facts are scoped.\n"
        candidate = (
            '<div align="center">\n<h1>CodeQA</h1>\n</div>\n'
            "## Scope boundary\n\nThe facts are scoped.\n"
        )
        audit = audit_markdown_v02(source, candidate, budget=LENIENT)
        self.assertIn("LEGACY_ANCHOR_REMOVED", audit.issues)
        self.assertEqual(audit.missing_anchors, ("codeqa",))
        with self.assertRaisesRegex(RefinementError, "LEGACY_ANCHOR_REMOVED"):
            enforce_markdown_v02(source, candidate, budget=LENIENT)

    def test_explicit_anchor_alias_preserves_legacy_heading(self):
        source = "# CodeQA\n\n## Scope boundary\n"
        candidate = (
            '<a name="codeqa"></a>\n\n<div align="center">\n'
            "<h1>CodeQA</h1>\n</div>\n\n## Scope boundary\n"
        )
        audit = enforce_markdown_v02(source, candidate, budget=LENIENT)
        self.assertTrue(audit.passed)
        self.assertEqual(audit.missing_anchors, ())

    def test_preserves_duplicate_heading_ids(self):
        old = "## Features\n\n## Features\n"
        newer = "## Features\n"
        self.assertEqual(heading_anchors(old), frozenset({"features", "features-1"}))
        audit = audit_markdown_v02(old, newer, budget=LENIENT)
        self.assertEqual(audit.missing_anchors, ("features-1",))

    def test_ignores_fenced_code_which_looks_like_heading_or_table(self):
        old = "~~~md\n# Fictional\n| " + "x" * 500 + " |\n~~~\n# Real\n"
        new = "~~~md\n# Fictional\n| " + "x" * 500 + " |\n~~~\n# Real\n"
        audit = enforce_markdown_v02(old, new)
        self.assertTrue(audit.passed)
        self.assertEqual(heading_anchors(old), frozenset({"real"}))
        self.assertEqual(audit.longest_table_row, 0)

    def test_markdown_inline_links_and_setext_headers_have_anchors(self):
        body = "## [Quality](docs/quality.md) & Scope\n\nOther Header\n------------\n"
        self.assertEqual(
            heading_anchors(body),
            frozenset({"quality--scope", "other-header"}),
        )

    def test_detects_removed_link_with_duplicate_counts(self):
        baseline = "# Docs\n\n[One](a.md) and [Two](a.md)\n"
        candidate = "# Docs\n\n[One](a.md)\n"
        audit = audit_markdown_v02(baseline, candidate, budget=LENIENT)
        self.assertIn("LINK_TARGET_REMOVED", audit.issues)
        self.assertEqual(audit.missing_link_targets, ("a.md",))

    def test_detects_invalid_local_fragment(self):
        baseline = "## Existing\n"
        candidate = "## Existing\n\n<a href=\"#unknown\">broken</a>\n"
        audit = audit_markdown_v02(baseline, candidate, budget=LENIENT)
        self.assertIn("LOCAL_FRAGMENT_UNRESOLVED", audit.issues)

    def test_detects_growth_and_wide_tables(self):
        baseline = "## Reference\n\nShort.\n"
        candidate = "## Reference\n\n" + "| " + "X" * 290 + " |\n" + "Long. " * 60
        budget = ReadabilityBudget(
            max_character_growth_ratio=2.0,
            max_line_growth_ratio=5.0,
            max_table_row_chars=200,
        )
        audit = audit_markdown_v02(baseline, candidate, budget=budget)
        self.assertIn("CHARACTER_BUDGET_EXCEEDED", audit.issues)
        self.assertIn("TABLE_ROW_TOO_WIDE", audit.issues)
        self.assertGreater(audit.longest_table_row, 200)

    def test_detects_line_growth_independent_of_characters(self):
        baseline = "# Title\n\nSome text content here.\n"
        candidate = "# Title\n\nSome\ntext\ncontent\nhere.\n\nMore\n"
        budget = ReadabilityBudget(
            max_character_growth_ratio=10,
            max_line_growth_ratio=1.5,
            max_table_row_chars=240,
        )
        audit = audit_markdown_v02(baseline, candidate, budget=budget)
        self.assertIn("LINE_BUDGET_EXCEEDED", audit.issues)

    def test_invalid_budget_rejected(self):
        for budget in (
            ReadabilityBudget(max_character_growth_ratio=0.9),
            ReadabilityBudget(max_line_growth_ratio=float("nan")),
            ReadabilityBudget(max_table_row_chars=10),
        ):
            with self.subTest(budget=budget):
                with self.assertRaises(RefinementError):
                    audit_markdown_v02("# Docs\n", "# Docs\n", budget=budget)

    def test_no_silent_override_of_semantic_review(self):
        baseline = "# Contract\n\nA required review is not a PASS.\n"
        self.assertTrue(enforce_markdown_v02(baseline, baseline).passed)
        # This audit does not prove semantic equivalence, and callers must
        # separately enforce required claims through v0.1 and human review.


if __name__ == "__main__":
    unittest.main()
