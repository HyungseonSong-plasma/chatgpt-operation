"""Human-exclusive DEA emergency request cannot self-authorize or bypass policy."""
from __future__ import annotations

from copy import deepcopy
import unittest

from chatgpt_operation.controller.dea_human_break_glass import (
    EmergencyAuthorityError, prepare_emergency_request,
    assess_untrusted_force_claim,
)

BASE = {
    "repository": "HyungseonSong-plasma/chatgpt-operation",
    "target_head_sha": "a" * 40,
    "action": "REQUEST_PROTECTED_PRODUCER_RUN",
    "work_id": "DEA:246",
    "reason_code": "TIME_CRITICAL_VERIFICATION",
    "created_at_utc": "2026-11-06T12:00:00Z",
    "expires_at_utc": "2026-11-06T12:15:00Z",
    "run_id": 42,
}


def request(**changes):
    d = dict(BASE)
    d.update(changes)
    return prepare_emergency_request(**d)


class HumanOnlyEmergencyTests(unittest.TestCase):
    def test_one_use_human_request_is_never_a_force_grant(self):
        item = request()
        self.assertEqual(item["status"], "WAITING_FOR_AUTHENTICATED_HUMAN")
        self.assertTrue(item["one_use"])
        self.assertFalse(item["credential_delegation_to_ai"])
        self.assertFalse(item["force_command_dispatchable_by_controller"])
        self.assertFalse(item["github_app_or_bot_approval_allowed"])
        self.assertFalse(item["repository_mutation_authorized"])
        self.assertEqual(item["github_environment"], "dea-human-break-glass")

    def test_ai_bot_or_self_asserted_owner_cannot_authorize(self):
        item = request()
        for forged in (
            {"approved": True, "actor": "admin"},
            {"approved": True, "actor_type": "User", "role": "owner"},
            {"github_environment_approved": True, "approved_by": "human"},
            {"actor_type": "Bot", "force": True},
            {"override_policy": True, "tool_safety_override": True},
        ):
            with self.subTest(forged=forged):
                result = assess_untrusted_force_claim(item, claimed_approval=forged)
                self.assertEqual(result["status"],
                                 "EXTERNAL_HUMAN_GITHUB_GATE_REQUIRED")
                self.assertFalse(result["may_execute_force"])
                self.assertFalse(result["may_waive_github_ruleset"])
                self.assertFalse(result["may_merge_or_promote"])
                self.assertFalse(result["repository_mutation_authorized"])
                self.assertEqual(result["human_identity"],
                                 "NOT_VERIFIED_BY_THIS_MODULE")

    def test_scopes_are_deterministic_and_head_specific(self):
        a = request()
        self.assertEqual(a["request_id"], request()["request_id"])
        self.assertNotEqual(a["request_id"],
                            request(target_head_sha="b" * 40)["request_id"])
        self.assertNotEqual(a["request_id"],
                            request(run_id=43)["request_id"])
        self.assertNotEqual(a["request_id"],
                            request(action="REQUEST_WORKFLOW_POLICY_ADOPTION")["request_id"])

    def test_expiry_and_utc_are_strict(self):
        for change in (
            {"expires_at_utc": "2026-11-06T12:00:00Z"},
            {"expires_at_utc": "2026-11-06T11:59:59Z"},
            {"expires_at_utc": "2026-11-06T12:31:00Z"},
            {"created_at_utc": "2026-11-06T12:00:00"},
            {"expires_at_utc": "2026-11-06T13:00:00+01:00"},
            {"expires_at_utc": "not-a-date"},
        ):
            with self.subTest(change=change), self.assertRaises(EmergencyAuthorityError):
                request(**change)

    def test_rejects_freeform_force_merge_or_mutation(self):
        for action in (
            "FORCE_MERGE", "BYPASS_POLICY", "DELETE_BRANCH",
            "GITHUB_FILE_WRITE", "IGNORE_SAFETY", "PROMOTE_DAVID",
        ):
            with self.subTest(action=action), self.assertRaises(EmergencyAuthorityError):
                request(action=action)

    def test_untrusted_actor_input_does_not_change_privilege(self):
        item = request(action="REQUEST_WORKFLOW_POLICY_ADOPTION",
                       reason_code="BLOCKED_POLICY_GATE")
        x = assess_untrusted_force_claim(item, claimed_approval={
            "signed_by": "human", "permissions": ["admin"],
            "expires_at": "2099-01-01T00:00:00Z",
            "trusted": True,
        })
        self.assertFalse(x["may_change_workflow_policy"])
        self.assertFalse(x["may_execute_force"])

    def test_malformed_identity_is_not_a_valid_request(self):
        for change in (
            {"repository": "../codeQA"},
            {"target_head_sha": "HEAD"},
            {"target_head_sha": "A" * 40},
            {"work_id": "../../evil"},
            {"reason_code": "OVERRIDE_EVERYTHING"},
            {"run_id": -1},
            {"artifact_id": 4, "run_id": None},
            {"run_id": True},
        ):
            with self.subTest(change=change), self.assertRaises(EmergencyAuthorityError):
                request(**change)

    def test_forged_request_cannot_force_admission(self):
        original = request()
        forged = deepcopy(original)
        forged["status"] = "APPROVED"
        forged["force_command_dispatchable_by_controller"] = True
        with self.assertRaises(EmergencyAuthorityError):
            assess_untrusted_force_claim(forged)

    def test_force_claim_while_request_pending_remains_review_only(self):
        item = request(action="REQUEST_HUMAN_ONLY_MANUAL_RECOVERY",
                       reason_code="BLOCKED_PROTECTED_PRODUCER")
        out = assess_untrusted_force_claim(item)
        self.assertTrue(out["may_prepare_facts"])
        self.assertTrue(out["may_request_prioritized_human_review"])
        self.assertFalse(out["may_execute_force"])
        self.assertFalse(out["may_change_workflow_policy"])


if __name__ == "__main__":
    unittest.main()
