"""Adversarial opt-in Mermaid documentation renderer regression tests."""

from __future__ import annotations

from copy import deepcopy
import unittest

from chatgpt_operation.documentation import (
    RefinementError,
    refine_document,
    render_evidence_diagram,
)


SHA = "a" * 40
P1 = "contracts/ccg/graph-v0.1.schema.json"
P2 = "contracts/qa/result-v0.1.schema.json"
INVENTORY = frozenset({"contracts/README.md", P1, P2})


def diagram() -> dict:
    return {
        "title": "Facts to findings",
        "caption": "Evidence flow described by the caller.",
        "nodes": [
            {"id": "ccg", "label": "CCG facts", "evidence_path": P1},
            {"id": "qa", "label": "QA findings", "evidence_path": P2},
        ],
        "edges": [
            {"source": "ccg", "target": "qa", "label": "scoped input",
             "evidence_path": P2},
        ],
    }


def payload() -> dict:
    return {
        "snapshot_sha": SHA,
        "document_path": "contracts/README.md",
        "title": "Contracts",
        "tagline": "Typed evidence",
        "introduction": "Versioned contracts",
        "sections": [{
            "key": "ccg", "title": "Graph", "subtitle": "Facts",
            "entries": [{
                "label": "Graph", "href": "ccg/graph-v0.1.schema.json",
                "description": "Source facts only.", "evidence_path": P1,
            }],
        }],
        "closing": "No universal quality PASS.",
    }


def refine(diagram_arg=None):
    return refine_document(
        payload=payload(), source_inventory=INVENTORY,
        inventory_complete=True, baseline_markdown=(
            "[Graph](ccg/graph-v0.1.schema.json)\nSource facts only."
        ), required_claims=["Source facts only."], preset="minimal",
        diagram=diagram_arg,
    )


class DocumentationDiagramV02Tests(unittest.TestCase):
    def test_opt_in_and_preservation(self):
        old = refine()
        result = refine(diagram())
        self.assertNotIn("mermaid", old.markdown)
        self.assertIn("mermaid", result.markdown)
        self.assertIn("flowchart LR", result.markdown)
        self.assertIn('n_ccg["CCG facts"]', result.markdown)
        self.assertIn("n_ccg -->|scoped input| n_qa", result.markdown)
        self.assertIn("Source witnesses", result.markdown)
        self.assertIn("not proof of runtime calls", result.markdown)
        self.assertEqual(result.preserved_link_count, old.preserved_link_count)
        self.assertEqual(result.preserved_claim_count, old.preserved_claim_count)
        self.assertEqual(result.snapshot_sha, old.snapshot_sha)

    def test_deterministic_order_independent_of_input_order(self):
        spec = diagram()
        other = deepcopy(spec)
        other["nodes"].reverse()
        self.assertEqual(
            render_evidence_diagram(spec, inventory=INVENTORY),
            render_evidence_diagram(other, inventory=INVENTORY),
        )

    def test_rejects_invented_or_untracked_witness(self):
        for where in ("nodes", "edges"):
            with self.subTest(where=where):
                changed = diagram()
                changed[where][0]["evidence_path"] = "outside/not-a-source.py"
                with self.assertRaisesRegex(RefinementError, "source inventory"):
                    render_evidence_diagram(changed, inventory=INVENTORY)

    def test_rejects_unsafe_or_unknown_endpoint(self):
        for invalid in ("bad-name", "end", "a; click bad", "A\nB", ""):
            with self.subTest(node_id=invalid):
                spec = diagram()
                spec["nodes"][0]["id"] = invalid
                # "end" is syntactically safe, but is a Mermaid keyword;
                # only prefixed node names are rendered, so it is permitted.
                if invalid == "end":
                    self.assertIn("n_end", render_evidence_diagram(
                        spec | {"edges": [{"source": "end", "target": "qa",
                                           "label": "scoped input", "evidence_path": P2}]},
                        inventory=INVENTORY,
                    ))
                    continue
                with self.assertRaises(RefinementError):
                    render_evidence_diagram(spec, inventory=INVENTORY)
        spec = diagram()
        spec["edges"][0]["target"] = "unknown"
        with self.assertRaisesRegex(RefinementError, "distinct declared nodes"):
            render_evidence_diagram(spec, inventory=INVENTORY)

    def test_fail_closed_duplicates_and_unexpected_keys(self):
        for invalid in ("node", "edge", "extra"):
            with self.subTest(invalid=invalid):
                spec = diagram()
                if invalid == "node":
                    spec["nodes"].append(deepcopy(spec["nodes"][0]))
                elif invalid == "edge":
                    spec["edges"].append(deepcopy(spec["edges"][0]))
                else:
                    spec["directives"] = "click qa javascript:alert(1)"
                with self.assertRaises(RefinementError):
                    render_evidence_diagram(spec, inventory=INVENTORY)

    def test_no_raw_mermaid_injection(self):
        spec = diagram()
        spec["nodes"][0]["label"] = 'x"]\nclick attacker https://example.org'
        with self.assertRaises(RefinementError):
            render_evidence_diagram(spec, inventory=INVENTORY)
        spec = diagram()
        spec["nodes"][0]["label"] = 'x"]|<script>%'
        output = render_evidence_diagram(spec, inventory=INVENTORY)
        self.assertNotIn("<script>", output)
        self.assertNotIn('x"]|', output)
        self.assertIn("&quot;", output)
        self.assertIn("&#124;", output)

    def test_rejects_missing_graph_and_control_characters(self):
        spec = diagram()
        spec["nodes"] = []
        with self.assertRaises(RefinementError):
            render_evidence_diagram(spec, inventory=INVENTORY)
        spec = diagram()
        spec["caption"] = "Confusing\u202eBIDI"
        with self.assertRaises(RefinementError):
            render_evidence_diagram(spec, inventory=INVENTORY)

    def test_no_source_truth_claim_when_inventory_attested(self):
        output = render_evidence_diagram(diagram(), inventory=INVENTORY)
        self.assertIn("caller-attested, not independently verified", output)
        self.assertIn("not proof of runtime calls", output)


if __name__ == "__main__":
    unittest.main()
