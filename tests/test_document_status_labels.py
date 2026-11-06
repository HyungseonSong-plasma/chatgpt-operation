"""Fail-closed tests for Samuel documentation-status display consistency."""

from __future__ import annotations

import unittest
from xml.etree import ElementTree

from chatgpt_operation.documentation.status_labels import (
    AXES, STATUS_COLORS, BADGE_PALETTE, LabelError, badge_filename, render_badge_svg,
    render_badge_header, audit_document_labels,
)

SHA = "a" * 40
DOC = "docs/architecture.md"
LABELS = {
    "decision": "ADOPTED",
    "implementation": "NOT_EVALUATED",
    "review": "NOT_EVALUATED",
}


def fixture() -> dict:
    assets = {
        "docs/assets/document-status/" + badge_filename(axis, value):
        render_badge_svg(axis, value)
        for axis, value in LABELS.items()
    }
    markdown = (
        "# Architecture\n\n"
        + render_badge_header(LABELS, asset_dir="assets/document-status")
        + "\n\nExample.\n"
    )
    return {
        "markdown": markdown,
        "document_path": DOC,
        "labels": LABELS,
        "snapshot_sha": SHA,
        "source_inventory": [DOC, *assets],
        "inventory_complete": True,
        "badge_sources": assets,
    }


class DocumentStatusLabelTests(unittest.TestCase):
    def test_every_badge_is_deterministic_accessible_local_svg(self):
        for axis in AXES:
            for value, color in STATUS_COLORS[axis].items():
                with self.subTest(axis=axis, value=value):
                    svg = render_badge_svg(axis, value)
                    self.assertEqual(svg, render_badge_svg(axis, value))
                    background, ink, border = BADGE_PALETTE[color]
                    self.assertIn(f'fill="#{background}"', svg)
                    self.assertIn(f'fill="#{ink}"', svg)
                    self.assertIn(f'stroke="#{border}"', svg)
                    self.assertEqual(ElementTree.fromstring(svg).attrib["role"], "img")
                    self.assertNotIn("img.shields.io", svg)
                    self.assertIn('height="22"', svg)
                    self.assertIn('rx="11"', svg)
                    self.assertEqual(svg.count("<rect "), 1)
                    self.assertIn(f'>{value}</text>', svg)

    def test_exact_header_match_never_claims_semantic_proof(self):
        result = audit_document_labels(**fixture())
        self.assertEqual(result.status, "MATCH")
        self.assertEqual(result.semantic_status, "NOT_EVALUATED")
        self.assertEqual(result.issues, ())

    def test_wrong_declared_status_does_not_silently_promote(self):
        args = fixture()
        args["labels"] = dict(LABELS, implementation="IMPLEMENTED")
        result = audit_document_labels(**args)
        self.assertEqual(result.status, "MISMATCH")
        self.assertTrue(any("implementation badge differs" in s for s in result.issues))

    def test_mutated_palette_is_rejected(self):
        args = fixture()
        path = "docs/assets/document-status/decision-adopted.svg"
        args["badge_sources"][path] = args["badge_sources"][path].replace("DAFBE1", "FFEBE9")
        self.assertEqual(audit_document_labels(**args).status, "MISMATCH")

    def test_missing_asset_in_inventory_is_rejected(self):
        args = fixture()
        args["source_inventory"] = [DOC]
        self.assertEqual(audit_document_labels(**args).status, "MISMATCH")

    def test_header_not_at_top_is_rejected(self):
        args = fixture()
        badge_line = args["markdown"].splitlines()[2]
        args["markdown"] = "# Architecture\n\n" + ("body\n" * 11) + badge_line
        self.assertEqual(audit_document_labels(**args).status, "MISMATCH")

    def test_pilot_row_without_blank_line_is_valid(self):
        args = fixture()
        args["markdown"] = args["markdown"].replace("# Architecture\n\n", "# Architecture\n", 1)
        self.assertEqual(audit_document_labels(**args).status, "MATCH")

    def test_paragraph_between_h1_and_badges_is_rejected(self):
        args = fixture()
        args["markdown"] = args["markdown"].replace(
            "# Architecture\n\n", "# Architecture\n\nA paragraph.\n\n", 1
        )
        self.assertEqual(audit_document_labels(**args).status, "MISMATCH")

    def test_fenced_code_badges_are_not_a_header(self):
        args = fixture()
        args["markdown"] = args["markdown"].replace(
            "# Architecture\n\n", "# Architecture\n\n```markdown\n", 1
        ) + "```\n"
        self.assertEqual(audit_document_labels(**args).status, "MISMATCH")

    def test_duplicate_badge_outside_canonical_row_is_rejected(self):
        args = fixture()
        row = args["markdown"].splitlines()[2]
        args["markdown"] = args["markdown"].replace(
            row + "\n\n", row + "\n" + row + "\n\n", 1
        )
        self.assertEqual(audit_document_labels(**args).status, "MISMATCH")

    def test_four_banners_or_extra_text_in_header_rejected(self):
        args = fixture()
        row = args["markdown"].splitlines()[2]
        import re
        images = re.findall(r"!\[[^\]]+\]\([^)]+\)", row)
        self.assertEqual(len(images), 3)
        first = images[0]
        for modified in (row + " " + first, "See: " + row, row + " explanation"):
            with self.subTest(modified=modified):
                changed = dict(args, markdown=args["markdown"].replace(row, modified, 1))
                self.assertEqual(audit_document_labels(**changed).status, "MISMATCH")

    def test_reordered_axes_rejected_even_if_each_status_valid(self):
        args = fixture()
        row = args["markdown"].splitlines()[2]
        import re
        images = re.findall(r"!\[[^\]]+\]\([^)]+\)", row)
        self.assertEqual(len(images), 3)
        args["markdown"] = args["markdown"].replace(row, " ".join(reversed(images)), 1)
        self.assertEqual(audit_document_labels(**args).status, "MISMATCH")

    def test_extra_blank_line_before_badges_is_rejected(self):
        args = fixture()
        args["markdown"] = args["markdown"].replace(
            "# Architecture\n\n", "# Architecture\n\n\n", 1
        )
        self.assertEqual(audit_document_labels(**args).status, "MISMATCH")

    def test_body_image_is_not_mistaken_for_header(self):
        args = fixture()
        row = args["markdown"].splitlines()[2]
        args["markdown"] = "# Architecture\n\nSome text.\n" + row
        self.assertEqual(audit_document_labels(**args).status, "MISMATCH")

    def test_skill_is_on_demand_and_not_in_init(self):
        import json
        from pathlib import Path
        from chatgpt_operation.skill_catalog import resolve_triggers

        catalog = json.loads(Path("skills/catalog.json").read_text(encoding="utf-8"))
        active = resolve_triggers(catalog, ["DOCUMENTATION_CONSISTENCY_QA"])
        self.assertEqual(active["status"], "RESOLVED")
        self.assertEqual(active["skills"][0]["name"], "document-consistency")
        init = resolve_triggers(catalog, ["INIT"])
        self.assertNotIn(
            "document-consistency", [entry["name"] for entry in init["skills"]]
        )

    def test_snapshot_and_inventory_fail_closed(self):
        args = fixture()
        args["snapshot_sha"] = "main"
        with self.assertRaises(LabelError):
            audit_document_labels(**args)
        args = fixture()
        args["inventory_complete"] = False
        with self.assertRaises(LabelError):
            audit_document_labels(**args)

    def test_unknown_label_and_unsafe_path_fail_closed(self):
        with self.assertRaises(LabelError):
            render_badge_svg("decision", "<svg>")
        with self.assertRaises(LabelError):
            render_badge_header(LABELS, asset_dir="https://badges.io")
        args = fixture()
        args["document_path"] = "../../escaped.md"
        with self.assertRaises(LabelError):
            audit_document_labels(**args)


if __name__ == "__main__":
    unittest.main()
