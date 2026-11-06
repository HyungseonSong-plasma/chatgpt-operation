"""Fail-closed admission guard for the owner-selected DEA v0.2 codeQA pilot.

This is an executable manifest sanity check, not a source/CI attestator.
No runner, repository writer, or branch-creation authority is exposed here.
"""
from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/dea-v02-codeqa-document-reference-pilot.json"


def assess_admission(data: dict) -> tuple[str, tuple[str, ...]]:
    if data.get("schema_version") != 1 or data.get("contract_id") != (
        "dea.v0.2.codeqa.documentation-reference-impact.pilot"
    ):
        return "BLOCKED_INVALID_CONTRACT", ("schema_version_or_contract_id",)
    scope = data.get("work_scope", {})
    if scope.get("repository") != "HyungseonSong-plasma/codeQA" or (
        scope.get("issue") != 288 or
        scope.get("subtask") != "phase-2-documentation-reference-impact-audit"
    ):
        return "BLOCKED_INVALID_CONTRACT", ("work_scope",)
    choices = data.get("candidate_strategies", [])
    if [(x.get("id"), x.get("kind")) for x in choices] != [
        ("A", "FULL_SCAN"), ("B", "REFERENCE_GRAPH"), ("C", "INCREMENTAL_INDEX")
    ]:
        return "BLOCKED_INVALID_CONTRACT", ("candidate_set",)
    if data.get("baseline", {}).get("candidate_count") != 3 or not data.get(
        "baseline", {}).get("unchanged_baseline"):
        return "BLOCKED_INVALID_CONTRACT", ("baseline",)
    checks = data.get("admission", {})
    needed = (
        "confirmed_task", "independent_review_complete",
        "phase1_adopted_exact_commit", "trusted_semantic_oracle_ready",
        "evidence_origin_verified", "matched_budget_frozen",
    )
    if set(checks) != set(needed) | {"branch_creation_authorized", "merge_authorized"}:
        return "BLOCKED_INVALID_CONTRACT", ("admission_fields",)
    if any(type(checks[k]) is not bool for k in checks):
        return "BLOCKED_INVALID_CONTRACT", ("admission_boolean_types",)
    pending = tuple(k for k in needed if checks[k] is not True)
    # Admission flags are descriptive, not self-granting authorization.
    if checks["branch_creation_authorized"] or checks["merge_authorized"]:
        return "BLOCKED_INVALID_CONTRACT", ("self_granted_authority",)
    if pending:
        return "BLOCKED_PREREQUISITES", pending
    return "REVIEW_REQUIRED_NO_WRITE_AUTHORITY", ()


class DocumentationPilotContractTests(unittest.TestCase):
    def test_selected_task_and_three_competing_methods(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest["work_scope"]["issue"], 288)
        self.assertEqual(manifest["baseline"]["source_commit_sha"], None)
        self.assertEqual(manifest["baseline"]["candidate_count"], 3)
        self.assertEqual(assess_admission(manifest)[0], "BLOCKED_PREREQUISITES")

    def test_owner_selection_cannot_grant_branch_or_merge_authority(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        manifest["admission"].update({
            "independent_review_complete": True,
            "phase1_adopted_exact_commit": True,
            "trusted_semantic_oracle_ready": True,
            "evidence_origin_verified": True,
            "matched_budget_frozen": True,
        })
        self.assertEqual(assess_admission(manifest)[0], "REVIEW_REQUIRED_NO_WRITE_AUTHORITY")
        manifest["admission"]["branch_creation_authorized"] = True
        self.assertEqual(assess_admission(manifest)[0], "BLOCKED_INVALID_CONTRACT")

    def test_incomplete_or_wrong_scope_rejected(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        manifest["candidate_strategies"].pop()
        self.assertEqual(assess_admission(manifest)[0], "BLOCKED_INVALID_CONTRACT")
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        manifest["work_scope"]["issue"] = 246
        self.assertEqual(assess_admission(manifest)[0], "BLOCKED_INVALID_CONTRACT")

    def test_per_candidate_missing_semantic_evidence_cannot_be_pass(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertTrue(manifest["fitness"]["hard_gate_fail_or_unknown_excludes"])
        self.assertTrue(manifest["fitness"]["no_aggregate_score"])
        self.assertIn("complete_known_internal_consumers",
                      manifest["common_oracle"]["semantic_hard_gates"])
        self.assertIn("no_doc_mutation", manifest["common_oracle"]["semantic_hard_gates"])


if __name__ == "__main__":
    unittest.main()
