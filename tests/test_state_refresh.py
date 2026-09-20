from __future__ import annotations

import unittest

from chatgpt_operation.controller.state_refresh import StateRefreshError, evaluate


def snapshot() -> dict:
    return {
        "schema_version": 1,
        "checkpoint": {
            "present": True,
            "trustworthy": True,
            "phase_changed": False,
            "rule_revision_changed": False,
            "scope_changed": False,
            "evidence_contradiction": False,
            "next_action_known": True,
        },
        "surfaces": [
            {
                "id": "active_pr",
                "stability": "MUTABLE",
                "locator_kind": "FLOATING",
                "decision_critical": True,
                "pin_verified": False,
                "checkpoint_fingerprint": "head:a",
                "current_fingerprint": "head:a",
                "probe_state": "OK",
                "probe_reads": ["pr.identity"],
                "detail_reads": ["pr.reviews", "ci.exact_head"],
                "prewrite_reads": ["pr.authoritative"],
            }
        ],
        "planned_mutations": [],
    }


class StateRefreshTests(unittest.TestCase):
    def test_untrusted_checkpoint_requires_full_refresh(self):
        data = snapshot()
        data["checkpoint"]["trustworthy"] = False
        result = evaluate(data)
        self.assertEqual(result["status"], "FULL_REFRESH_REQUIRED")
        self.assertFalse(result["can_use_checkpoint"])

    def test_phase_or_rule_change_requires_full_refresh(self):
        for field in ("phase_changed", "rule_revision_changed", "scope_changed"):
            with self.subTest(field=field):
                data = snapshot()
                data["checkpoint"][field] = True
                self.assertEqual(evaluate(data)["status"], "FULL_REFRESH_REQUIRED")

    def test_unprobed_mutable_surface_requests_only_probe_reads(self):
        data = snapshot()
        data["surfaces"][0]["probe_state"] = "NOT_RUN"
        data["surfaces"][0]["current_fingerprint"] = None
        result = evaluate(data)
        self.assertEqual(result["status"], "PROBE_REQUIRED")
        self.assertEqual(result["probe_reads"], ["pr.identity"])
        self.assertEqual(result["expand_reads"], [])

    def test_unchanged_mutable_surface_skips_detail_reads(self):
        result = evaluate(snapshot())
        self.assertEqual(result["status"], "CHECKPOINT_CURRENT")
        self.assertEqual(result["expand_reads"], [])
        self.assertEqual(result["skipped_surfaces"], ["active_pr"])

    def test_changed_mutable_surface_expands_only_its_details(self):
        data = snapshot()
        data["surfaces"][0]["current_fingerprint"] = "head:b"
        result = evaluate(data)
        self.assertEqual(result["status"], "DELTA_REFRESH")
        self.assertEqual(result["changed_surfaces"], ["active_pr"])
        self.assertEqual(result["expand_reads"], ["pr.reviews", "ci.exact_head"])

    def test_verified_exact_pin_is_skipped_without_probe(self):
        data = snapshot()
        data["surfaces"].append(
            {
                "id": "sol_pin",
                "stability": "PINNED_IMMUTABLE",
                "locator_kind": "EXACT",
                "decision_critical": True,
                "pin_verified": True,
                "checkpoint_fingerprint": "sha:abc",
                "current_fingerprint": None,
                "probe_state": "NOT_RUN",
                "probe_reads": ["sol.commit"],
                "detail_reads": ["sol.runtime"],
                "prewrite_reads": [],
            }
        )
        result = evaluate(data)
        self.assertEqual(result["status"], "CHECKPOINT_CURRENT")
        self.assertEqual(result["probe_reads"], [])
        self.assertIn("sol_pin", result["skipped_surfaces"])

    def test_floating_ref_cannot_be_declared_pinned_immutable(self):
        data = snapshot()
        data["surfaces"][0].update(
            {
                "stability": "PINNED_IMMUTABLE",
                "locator_kind": "FLOATING",
                "pin_verified": True,
            }
        )
        with self.assertRaises(StateRefreshError):
            evaluate(data)

    def test_planned_mutation_always_requires_authoritative_prewrite(self):
        data = snapshot()
        data["planned_mutations"] = ["active_pr"]
        result = evaluate(data)
        self.assertEqual(result["status"], "PREWRITE_ONLY")
        self.assertEqual(result["prewrite_reads"], ["pr.authoritative"])

    def test_prewrite_requirement_survives_delta_refresh(self):
        data = snapshot()
        data["planned_mutations"] = ["active_pr"]
        data["surfaces"][0]["current_fingerprint"] = "head:b"
        result = evaluate(data)
        self.assertEqual(result["status"], "DELTA_REFRESH")
        self.assertEqual(result["prewrite_reads"], ["pr.authoritative"])

    def test_mutation_cannot_target_pinned_immutable_surface(self):
        data = snapshot()
        data["surfaces"].append(
            {
                "id": "sol_pin",
                "stability": "PINNED_IMMUTABLE",
                "locator_kind": "EXACT",
                "decision_critical": True,
                "pin_verified": True,
                "checkpoint_fingerprint": "sha:abc",
                "current_fingerprint": None,
                "probe_state": "NOT_RUN",
                "probe_reads": [],
                "detail_reads": [],
                "prewrite_reads": [],
            }
        )
        data["planned_mutations"] = ["sol_pin"]
        with self.assertRaises(StateRefreshError):
            evaluate(data)

    def test_probe_error_blocks_decision_instead_of_using_stale_state(self):
        data = snapshot()
        data["surfaces"][0]["probe_state"] = "ERROR"
        data["surfaces"][0]["current_fingerprint"] = None
        result = evaluate(data)
        self.assertEqual(result["status"], "PROBE_BLOCKED")
        self.assertEqual(result["next_action"], "repair_probe_or_hold")

    def test_noncritical_unmutated_surface_does_not_force_probe(self):
        data = snapshot()
        data["surfaces"].append(
            {
                "id": "background_issue",
                "stability": "MUTABLE",
                "locator_kind": "FLOATING",
                "decision_critical": False,
                "pin_verified": False,
                "checkpoint_fingerprint": "u:1",
                "current_fingerprint": None,
                "probe_state": "NOT_RUN",
                "probe_reads": ["issue.identity"],
                "detail_reads": ["issue.comments"],
                "prewrite_reads": ["issue.authoritative"],
            }
        )
        result = evaluate(data)
        self.assertEqual(result["status"], "CHECKPOINT_CURRENT")
        self.assertIn("background_issue", result["skipped_surfaces"])

    def test_unknown_mutation_surface_fails_closed(self):
        data = snapshot()
        data["planned_mutations"] = ["missing"]
        with self.assertRaises(StateRefreshError):
            evaluate(data)


if __name__ == "__main__":
    unittest.main()
