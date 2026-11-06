"""Fail-closed DEA environment preflight: no self-granted emergency authority."""
from __future__ import annotations

from copy import deepcopy
import unittest

from chatgpt_operation.controller.dea_environment_preflight import (
    assess_human_environment,
)

ENV = {
    "name": "dea-human-break-glass",
    "protection_rules": [{
        "type": "required_reviewers",
        "prevent_self_review": False,
        "reviewers": [{
            "type": "User", "reviewer": {"login": "human-operator"},
        }],
    }],
    "deployment_branch_policy": {
        "protected_branches": False, "custom_branch_policies": True,
    },
}
BRANCHES = {"total_count": 1, "branch_policies": [{"name": "main"}]}
RULES = [{
    "name": "dea-main-protection", "enforcement": "active",
    "target": "branch",
    "conditions": {"ref_name": {
        "include": ["refs/heads/main"], "exclude": [],
    }},
    "rules": [
        {"type": "pull_request"},
        {"type": "required_status_checks", "parameters": {
            "required_status_checks": [{"context": "test"}],
        }},
        {"type": "non_fast_forward"},
        {"type": "deletion"},
    ],
}]


def inspect(env=ENV, branches=BRANCHES, rules=RULES, humans=None):
    return assess_human_environment(
        env, branches, rules,
        nominated_human_logins={"human-operator"} if humans is None else humans,
    )


class ProtectedEnvironmentPreflightTests(unittest.TestCase):
    def test_complete_snapshot_cannot_activate_or_authorize(self):
        result = inspect()
        self.assertEqual(result["status"], "CONFIGURATION_SNAPSHOT_MATCH")
        self.assertEqual(result["missing_protections"], [])
        self.assertEqual(result["human_admin_bypass_setting"],
                         "REQUIRES_HUMAN_UI_CONFIRMATION")
        self.assertFalse(result["human_only_break_glass_active"])
        self.assertFalse(result["controller_force_execution_authorized"])
        self.assertFalse(result["repository_mutation_authorized"])

    def test_environment_creation_without_required_reviewer_is_insufficient(self):
        env = deepcopy(ENV)
        env["protection_rules"] = []
        out = inspect(env)
        self.assertEqual(out["status"], "CONFIGURATION_INCOMPLETE")
        self.assertIn("REQUIRED_REVIEWERS_NOT_CONFIGURED",
                      out["missing_protections"])

    def test_team_bot_or_unlisted_reviewer_is_not_human_only(self):
        for entries in (
            [{"type": "Team", "reviewer": {"login": "staff"}}],
            [{"type": "User", "reviewer": {"login": "automation[bot]"}}],
            [{"type": "User", "reviewer": {"login": "someone-else"}}],
            [],
        ):
            env = deepcopy(ENV)
            env["protection_rules"][0]["reviewers"] = entries
            with self.subTest(entries=entries):
                out = inspect(env)
                self.assertIn("REVIEWERS_NOT_EXACT_NAMED_HUMAN_ALLOWLIST",
                              out["missing_protections"])
                self.assertFalse(out["human_only_break_glass_active"])

    def test_extra_branch_or_wildcard_is_not_main_only(self):
        for entries in (
            [{"name": "main"}, {"name": "dev"}],
            [{"name": "*"}],
            [{"name": "releases/*"}],
            [],
        ):
            branches = {"total_count": len(entries),
                        "branch_policies": entries}
            out = inspect(branches=branches)
            self.assertIn("MAIN_ONLY_BRANCH_POLICY_NOT_VERIFIED",
                          out["missing_protections"])

    def test_absent_real_world_ruleset_still_blocks(self):
        out = inspect(rules=[])
        self.assertIn("MAIN_RULESET_WITH_CI_AND_PR_PROTECTION_NOT_VERIFIED",
                      out["missing_protections"])
        self.assertFalse(out["human_only_break_glass_active"])

    def test_inactive_or_broad_ruleset_does_not_qualify(self):
        for changes in (
            {"enforcement": "disabled"},
            {"conditions": {"ref_name": {
                "include": ["refs/heads/*"], "exclude": [],
            }}},
            {"rules": [{"type": "pull_request"}]},
        ):
            rules = deepcopy(RULES)
            rules[0].update(changes)
            out = inspect(rules=rules)
            self.assertIn("MAIN_RULESET_WITH_CI_AND_PR_PROTECTION_NOT_VERIFIED",
                          out["missing_protections"])

    def test_missing_required_ci_check_is_not_pass(self):
        rules = deepcopy(RULES)
        rules[0]["rules"][1]["parameters"]["required_status_checks"] = [
            {"context": "unrelated"},
        ]
        out = inspect(rules=rules)
        self.assertEqual(out["status"], "CONFIGURATION_INCOMPLETE")

    def test_no_trusted_external_identity_source_stays_unknown(self):
        env = deepcopy(ENV)
        env["approved"] = True
        env["github_human_identity_attested"] = True
        env["admins_can_bypass"] = False
        out = inspect(env)
        self.assertEqual(out["github_human_identity"],
                         "NOT_ATTESTED_BY_THIS_CHECK")
        self.assertEqual(out["human_admin_bypass_setting"],
                         "REQUIRES_HUMAN_UI_CONFIRMATION")
        self.assertFalse(out["human_only_break_glass_active"])

    def test_unrestricted_branch_setting_is_rejected(self):
        env = deepcopy(ENV)
        env["deployment_branch_policy"] = None
        out = inspect(env)
        self.assertIn("SELECTED_BRANCH_POLICY_REQUIRED",
                      out["missing_protections"])

    def test_missing_snapshots_cannot_assert_activation(self):
        out = inspect(env=None, branches=None, rules=None, humans=set())
        self.assertEqual(out["status"], "CONFIGURATION_INCOMPLETE")
        self.assertIn("ENVIRONMENT_NOT_VERIFIED", out["missing_protections"])
        self.assertIn("NAMED_HUMAN_ALLOWLIST_REQUIRED",
                      out["missing_protections"])
        self.assertFalse(out["repository_mutation_authorized"])


if __name__ == "__main__":
    unittest.main()
