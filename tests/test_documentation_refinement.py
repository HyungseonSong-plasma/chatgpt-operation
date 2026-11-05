from __future__ import annotations

import json
from pathlib import Path
import unittest

from chatgpt_operation.documentation import RefinementError, refine_document
from chatgpt_operation.skill_catalog import resolve_triggers


SHA = "a" * 40
FILE = "contracts/adapters/capability-v0.1.schema.json"
LINK = "adapters/capability-v0.1.schema.json"
PHRASE = "Declared adapter support and limits."


def payload() -> dict:
    return {
        "snapshot_sha": SHA,
        "document_path": "contracts/README.md",
        "title": "codeQA Contracts",
        "tagline": "Schemas define data structures.",
        "introduction": "Versioned contracts.",
        "sections": [{
            "key": "adapters",
            "title": "Adapters",
            "subtitle": "Language integration",
            "href": "adapters/",
            "entries": [{
                "label": "Capability",
                "href": LINK,
                "description": PHRASE,
                "evidence_path": FILE,
            }],
        }],
        "closing": "Only add designed contract areas.",
    }


def refine(**kwargs):
    args = dict(
        payload=payload(),
        source_inventory=["contracts/README.md", FILE],
        inventory_complete=True,
        baseline_markdown=f"[Capability]({LINK})\n\n{PHRASE}",
        required_claims=[PHRASE],
        preset="fastapi-astro",
    )
    args.update(kwargs)
    return refine_document(**args)


class DocumentationRefinementTests(unittest.TestCase):
    def test_presets_are_deterministic_and_preserve_links(self):
        for preset in ("fastapi-astro", "minimal"):
            with self.subTest(preset=preset):
                a = refine(preset=preset)
                b = refine(preset=preset)
                self.assertEqual(a, b)
                self.assertIn(f"]({LINK})", a.markdown)
                self.assertIn(PHRASE, a.markdown)
                self.assertEqual(a.preserved_link_count, 1)
                self.assertEqual(a.preserved_claim_count, 1)
                self.assertEqual(a.snapshot_sha, SHA)
                self.assertIn("Contract | Purpose", a.markdown)

    def test_unknown_design_is_rejected(self):
        with self.assertRaisesRegex(RefinementError, "unknown design"):
            refine(preset="unknown")

    def test_requires_exact_snapshot_and_complete_inventory(self):
        broken = payload()
        broken["snapshot_sha"] = "main"
        with self.assertRaisesRegex(RefinementError, "exact 40-hex"):
            refine(payload=broken)
        with self.assertRaisesRegex(RefinementError, "not attested complete"):
            refine(inventory_complete=False)

    def test_rejects_missing_or_duplicate_evidence_paths(self):
        with self.assertRaisesRegex(RefinementError, "witness missing"):
            refine(source_inventory=["contracts/README.md"])
        with self.assertRaisesRegex(RefinementError, "duplicates"):
            refine(source_inventory=["contracts/README.md", FILE, FILE])

    def test_rejects_removed_baseline_links(self):
        baseline = f"[Capability]({LINK}) and [Other](qa/result-v0.1.schema.json)"
        with self.assertRaisesRegex(RefinementError, "baseline links removed"):
            refine(baseline_markdown=baseline, required_claims=[])

    def test_rejects_missing_required_claim(self):
        with self.assertRaisesRegex(RefinementError, "required claim not preserved"):
            refine(required_claims=["This other semantic guarantee"])

    def test_rejects_unsafe_and_missing_link_targets(self):
        for bad in ("javascript:alert(1)", "http://example.com", "../../escape.md", "missing.md"):
            with self.subTest(bad=bad):
                broken = payload()
                broken["sections"][0]["entries"][0]["href"] = bad
                with self.assertRaises(RefinementError):
                    refine(payload=broken, baseline_markdown=PHRASE, required_claims=[PHRASE])

    def test_rejects_unscoped_document_path(self):
        broken = payload()
        broken["document_path"] = "../outside.md"
        with self.assertRaises(RefinementError):
            refine(payload=broken)

    def test_rejects_duplicate_sections(self):
        broken = payload()
        broken["sections"].append(dict(broken["sections"][0]))
        with self.assertRaisesRegex(RefinementError, "unique slugs"):
            refine(payload=broken)

    def test_compaction_does_not_remove_entries(self):
        broken = payload()
        broken["sections"][0]["entries"].append({
            "label": "Second",
            "href": LINK,
            "description": "Another  source   observation.",
            "evidence_path": FILE,
        })
        result = refine(payload=broken)
        self.assertIn("Another source observation.", result.markdown)
        self.assertEqual(result.markdown.count("](" + LINK + ")"), 2)

    def test_contract_and_catalog_are_registered_without_init_activation(self):
        contract = json.loads(
            Path("skills/documentation-refinement/contract.json").read_text()
        )
        self.assertEqual(contract["contract_id"], "samuel.documentation-refinement.v0.1")
        catalog = json.loads(Path("skills/catalog.json").read_text())
        result = resolve_triggers(catalog, ["DOCUMENTATION_REFINEMENT"])
        self.assertEqual(result["status"], "RESOLVED")
        self.assertEqual(result["skills"][0]["name"], "documentation-refinement")
        init = resolve_triggers(catalog, ["INIT"])
        self.assertNotIn(
            "documentation-refinement", [s["name"] for s in init["skills"]]
        )


if __name__ == "__main__":
    unittest.main()
