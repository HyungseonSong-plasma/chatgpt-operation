"""Evidence-bound release of #255's retired global state without erasing errors."""
from __future__ import annotations

import copy
import unittest

from chatgpt_operation.controller.closed_work_reconciliation import (
    BRANCH, EXPECTED_REF_SHA, ExternalReconciliationError,
    plan_external_noop_reconciliation,
)
from chatgpt_operation.controller.durable_state import (
    can_rollover_state, decode_state, encode_state, require_fresh_write,
)
from chatgpt_operation.controller.research import ResearchState

REPO = "HyungseonSong-plasma/chatgpt-operation"
FINGERPRINT = "5c12a213f3030f9bc4b9e6d8aab108fe5c43d448566ac5a04a8dbb3332227111"


def fail():
    return {
        "schema_version": 1, "fingerprint": FINGERPRINT,
        "work_id": "issue:255", "target_acceptance_criterion": None,
        "failure_class": "reasoning_validation",
        "status": "escalated", "occurrences": 2,
        "last_error": "OpenAI reasoning provider HTTP request failed",
        "node_attempts": None, "branch_identity": None,
        "capability_exhaustion_proven": False,
    }


def signed(ident, body, *, author="HyungseonSong-plasma", altered=False):
    return {
        "id": ident, "body": body,
        "user": {"login": author},
        "created_at": "2026-11-09T00:00:00Z",
        "updated_at": "2026-11-09T00:00:01Z" if altered
        else "2026-11-09T00:00:00Z",
    }


def fixtures():
    state = ResearchState("issue:255", "Exact-SHA Ruleset cleanup")
    state.revision = 2
    state.predispatch_failures = {FINGERPRINT: fail()}
    ledger = {
        "issue:255": {"work_id": "issue:255", "status": "reasoning_required"},
        "issue:256": {"work_id": "issue:256", "status": "admitted"},
    }
    params = {
        "repository": REPO,
        "source_main_sha": "a" * 40,
        "issue255": {
            "number": 255, "state": "closed",
            "body": f"Cleanup only {BRANCH} at {EXPECTED_REF_SHA}",
        },
        "issue256": {
            "number": 256, "state": "closed",
            "title": "[Samuel diagnostic A] Read-only reasoning baseline for branch-policy verification",
        },
        "comments255": [
            signed(6735864890,
                   f"NO_MUTATION_NEEDED {BRANCH} {EXPECTED_REF_SHA} ref 404"),
            signed(8888,
                   "<!-- samuel-closed-work-reconcile-release-v1 -->\n"
                   f"I authorize issue:255 and issue:256 closure. "
                   f"{BRANCH} {EXPECTED_REF_SHA} NO_MUTATION_NEEDED. "
                   "Please preserve escalation."),
        ],
        "comments256": [
            signed(
                6745233284,
                "<!-- samuel-256-diagnostic-closure-v1 --> "
                "provider 401 invalid_api_key; typed model DID NOT SUCCEED",
            ),
        ],
        "ref_absent": True, "branch_absent": True,
        "matching_refs_empty": True,
    }
    return state, ledger, params


class ClosedWorkReconciliationTests(unittest.TestCase):
    def valid(self):
        state, ledger, params = fixtures()
        result = plan_external_noop_reconciliation(state, ledger, **params)
        return state, ledger, params, result

    def test_reconciles_retirement_and_preserves_original_escalation(self):
        state, ledger, _, (proposed, admitted, proof) = self.valid()
        self.assertEqual(state.revision, 2)
        self.assertEqual(proposed.revision, 3)
        self.assertEqual(proposed.predispatch_failures, state.predispatch_failures)
        self.assertEqual(state.predispatch_failures[FINGERPRINT]["status"], "escalated")
        self.assertEqual(proposed.predispatch_failures[FINGERPRINT]["status"], "escalated")
        self.assertTrue(can_rollover_state(proposed))
        self.assertFalse(can_rollover_state(state))
        self.assertEqual(admitted["issue:255"]["status"], "complete")
        self.assertEqual(admitted["issue:256"]["status"], "complete")
        self.assertEqual(ledger["issue:256"]["status"], "admitted")
        self.assertEqual(proof["provider_executed"], False)
        self.assertEqual(proof["postcondition"], "NO_MUTATION_NEEDED")
        self.assertEqual(proof["owner_comment_id"], 8888)

    def test_durable_serialization_and_workload_rollover(self):
        _, _, _, (retired, _, _) = self.valid()
        restored = decode_state(encode_state(retired))
        self.assertTrue(can_rollover_state(restored))
        require_fresh_write(restored, ResearchState("issue:281", "New admitted work"))

    def test_missing_owner_approval_fails(self):
        s, l, p = fixtures()
        p["comments255"] = p["comments255"][:1]
        with self.assertRaises(ExternalReconciliationError):
            plan_external_noop_reconciliation(s, l, **p)

    def test_forged_approval_author_fails(self):
        s, l, p = fixtures()
        p["comments255"][1]["user"]["login"] = "attacker"
        with self.assertRaises(ExternalReconciliationError):
            plan_external_noop_reconciliation(s, l, **p)

    def test_edited_owner_comment_fails(self):
        s, l, p = fixtures()
        p["comments255"][1]["updated_at"] = "2026-11-09T00:01:00Z"
        with self.assertRaises(ExternalReconciliationError):
            plan_external_noop_reconciliation(s, l, **p)

    def test_branch_must_be_absent_by_three_sources(self):
        for field in ("ref_absent", "branch_absent", "matching_refs_empty"):
            s, l, p = fixtures()
            p[field] = False
            with self.subTest(field=field):
                with self.assertRaises(ExternalReconciliationError):
                    plan_external_noop_reconciliation(s, l, **p)

    def test_rev_or_historical_error_change_fails(self):
        for mutation in ("revision", "error", "status"):
            s, l, p = fixtures()
            if mutation == "revision":
                s.revision = 3
            if mutation == "error":
                s.predispatch_failures[FINGERPRINT]["last_error"] = "invented"
            if mutation == "status":
                s.predispatch_failures[FINGERPRINT]["status"] = "resolved"
            with self.subTest(mutation=mutation):
                with self.assertRaises(ExternalReconciliationError):
                    plan_external_noop_reconciliation(s, l, **p)

    def test_active_execution_blocks_retirement(self):
        s, l, p = fixtures()
        s.action_queue["action-1"] = {"status": "running"}
        with self.assertRaises(ExternalReconciliationError):
            plan_external_noop_reconciliation(s, l, **p)

    def test_open_source_issue_or_unclassified_provider_blocks(self):
        for mutation in ("open255", "open256", "unclassified256"):
            s, l, p = fixtures()
            if mutation == "open255": p["issue255"]["state"] = "open"
            if mutation == "open256": p["issue256"]["state"] = "open"
            if mutation == "unclassified256":
                p["comments256"][0]["body"] = "model PASSED"
            with self.subTest(mutation=mutation):
                with self.assertRaises(ExternalReconciliationError):
                    plan_external_noop_reconciliation(s, l, **p)

    def test_altered_durable_proof_cannot_release_slot(self):
        _, _, _, (retired, _, _) = self.valid()
        for mutation in ("fingerprint", "source", "owner", "absent"):
            case = copy.deepcopy(retired)
            proof = case.inherited_evidence[-1]
            if mutation == "fingerprint": proof["historical_failure_sha256"] = "0" * 64
            if mutation == "source": proof["expected_original_sha"] = "b" * 40
            if mutation == "owner": proof["owner_comment_id"] = 0
            if mutation == "absent": proof["ref_absent"] = False
            with self.subTest(mutation=mutation):
                self.assertFalse(can_rollover_state(case))

    def test_retirement_without_proof_never_releases_escalation(self):
        _, _, _, (retired, _, _) = self.valid()
        retired.inherited_evidence = []
        self.assertFalse(can_rollover_state(retired))

    def test_no_unrelated_admission_entry_may_be_preselected(self):
        s, l, p = fixtures()
        l["issue:281"] = {"status": "admitted", "work_id": "issue:281"}
        with self.assertRaises(ExternalReconciliationError):
            plan_external_noop_reconciliation(s, l, **p)


if __name__ == "__main__":
    unittest.main()
