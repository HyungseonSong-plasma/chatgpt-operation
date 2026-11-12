"""Guard the unprivileged activation draft; this does not activate Gemini."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path("automation/gemini-review")
POLICY = Path("automation/samuel/repository-mutation-policy.json")


class GeminiActivationProposalTests(unittest.TestCase):
    def setUp(self):
        self.plan = json.loads((ROOT / "activation-proposal-v0.1.json").read_text())
        self.workflow = (ROOT / "samuel-gemini-review.proposed.yml").read_text()
        self.policy = json.loads(POLICY.read_text())

    def test_policy_still_blocks_privileged_mutations(self):
        denied = self.policy["mutation"]["file_paths"]["deny"]
        self.assertIn("skills/capability-registry.json", denied)
        self.assertIn(".github/workflows/**", denied)
        self.assertEqual(self.plan["status"], "PROPOSED_ONLY_NOT_EXECUTABLE")
        self.assertFalse(self.plan["policy_gate"]["auto_override"])
        self.assertTrue(self.plan["policy_gate"]["owner_approved_privileged_installation_required"])
        self.assertNotIn("EXTERNAL_LLM_REVIEW", json.loads(
            Path("skills/capability-registry.json").read_text()
        )["capabilities"])

    def test_issue_route_authorizes_owner_only_and_denies_reruns(self):
        t = self.plan["trigger"]
        self.assertEqual(t["method"], "github_issue_label")
        self.assertEqual(t["label"], "samuel/gemini-review-approved")
        self.assertEqual(t["source_repository_allowlist"], ["HyungseonSong-plasma/codeQA"])
        self.assertTrue(t["single_owner_label_event"])
        self.assertEqual(t["run_attempt_must_equal"], 1)
        for fragment in (
            "types: [labeled]", "github.event.label.name",
            "github.actor == 'HyungseonSong-plasma'",
            "github.event.issue.user.login == 'HyungseonSong-plasma'",
            "github.run_attempt == 1", "samuel/gemini-review-approved",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.workflow)

    def test_separate_credential_scopes_and_exact_source_gate(self):
        self.assertIn("jobs:\n  prepare:", self.workflow)
        self.assertIn("\n  review:\n", self.workflow)
        prepare, review = self.workflow.split("\n  review:\n", 1)
        self.assertIn("GH_TOKEN: $" + "{{ github.token }}", prepare)
        self.assertNotIn("GEMINI_API_KEY:", prepare)
        self.assertNotIn("GH_TOKEN:", review)
        self.assertIn("GEMINI_API_KEY: $" + "{{ secrets.SAMUEL_GEMINI_API_KEY }}", review)
        self.assertIn("gemini_review_ingress", prepare)
        self.assertIn("gemini_review_receipt", review)
        self.assertIn("persist-credentials: false", review)
        self.assertIn("gemini-2.5-flash", review)
        self.assertIn("retention-days: 7", self.workflow)
        self.assertIn("--timeout 90", review)

    def test_model_has_no_github_or_merge_authority(self):
        self.assertFalse(self.plan["authority"]["gemini_can_access_github"])
        self.assertFalse(self.plan["authority"]["review_may_approve_merge"])
        self.assertFalse(self.plan["authority"]["review_result_is_semantic_pass"])
        self.assertEqual(
            self.plan["proposed_workflow"]["install_target"],
            ".github/workflows/samuel-gemini-review.yml",
        )


if __name__ == "__main__":
    unittest.main()
