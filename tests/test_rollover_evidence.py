import unittest

from chatgpt_operation.controller.research import ResearchState, ResearchStage
from chatgpt_operation.controller.rollover_evidence import inherited_evidence_for_issue


def completed(plan, *, status="pass", after=None, run_id=1):
    return {
        "status": "complete",
        "plan": plan,
        "completion_result": {
            "schema_version": 1,
            "research_id": "issue:44",
            "action_id": "fixture",
            "executor": plan["executor"],
            "status": status,
            "observation": "verified by postcondition readback",
            "retryable": False,
            "details": {
                "after": after or {},
                "provenance": {
                    "workflow_run_id": run_id,
                    "run_attempt": 1,
                    "head_sha": "a" * 40,
                    "action_id": "fixture",
                },
            },
        },
    }


class RolloverEvidenceTests(unittest.TestCase):
    def state(self):
        state = ResearchState(
            "issue:44",
            "terminal predecessor",
            stage=ResearchStage.EXECUTE,
        )
        state.action_queue = {
            "01-create-pr": completed({
                "schema_version": 1,
                "research_id": "issue:44",
                "stage": "implement",
                "executor": "github_native",
                "payload": {
                    "action": "create_pr",
                    "repository": "HyungseonSong-plasma/chatgpt-operation",
                    "target": {
                        "head": "samuel/issues-24-43",
                        "base": "main",
                        "title": "Telemetry maintenance",
                        "body": "Related issues: #24, #43, #44.",
                    },
                    "preconditions": {"pr_present": False},
                    "desired_postcondition": {"pr_present": True},
                },
                "expected_observation": "reviewable telemetry PR exists",
            }, after={"pr_present": True, "pr_number": 136, "head_sha": "b" * 40}),
            "02-file": completed({
                "schema_version": 1,
                "research_id": "issue:44",
                "stage": "implement",
                "executor": "repository_mutation",
                "payload": {
                    "schema_version": 1,
                    "repository": "HyungseonSong-plasma/chatgpt-operation",
                    "resource": "file",
                    "action": "create",
                    "target": {
                        "branch": "samuel/issues-24-43",
                        "path": "src/chatgpt_operation/weekly_maintenance.py",
                    },
                    "expected": {"absent": True},
                    "desired": {"content": "x=1\n"},
                },
                "expected_observation": "weekly maintenance implementation exists",
            }, after={
                "status": "PASS",
                "result_identity": "blob",
                "target": {
                    "branch": "samuel/issues-24-43",
                    "path": "src/chatgpt_operation/weekly_maintenance.py",
                },
            }),
            "03-merge": completed({
                "schema_version": 1,
                "research_id": "issue:44",
                "stage": "execute",
                "executor": "github_native",
                "payload": {
                    "action": "merge_pr",
                    "repository": "HyungseonSong-plasma/chatgpt-operation",
                    "target": {
                        "number": 136,
                        "expected_head_sha": "c" * 40,
                    },
                    "desired_postcondition": {"merged": True},
                },
                "expected_observation": "PR #136 merged",
            }, after={"merged": True, "head_sha": "c" * 40}),
            "04-unrelated": completed({
                "schema_version": 1,
                "research_id": "issue:44",
                "stage": "implement",
                "executor": "repository_mutation",
                "payload": {
                    "schema_version": 1,
                    "repository": "HyungseonSong-plasma/chatgpt-operation",
                    "resource": "file",
                    "action": "create",
                    "target": {
                        "branch": "samuel/unrelated",
                        "path": "unrelated.py",
                    },
                    "expected": {"absent": True},
                    "desired": {"content": "x=2\n"},
                },
                "expected_observation": "unrelated implementation exists",
            }),
        }
        return state

    def test_inherits_explicit_pr_branch_and_merge_chain(self):
        evidence = inherited_evidence_for_issue(self.state(), 24)
        self.assertEqual(
            [item["source_action_id"] for item in evidence],
            ["01-create-pr", "02-file", "03-merge"],
        )
        self.assertEqual(evidence[0]["target"]["head"], "samuel/issues-24-43")
        self.assertEqual(evidence[1]["target"]["path"], "src/chatgpt_operation/weekly_maintenance.py")
        self.assertTrue(evidence[2]["after"]["merged"])

    def test_does_not_inherit_unrelated_terminal_actions(self):
        evidence = inherited_evidence_for_issue(self.state(), 99)
        self.assertEqual(evidence, [])

    def test_rejected_or_failed_actions_are_not_positive_evidence(self):
        state = self.state()
        state.action_queue["03-merge"]["status"] = "rejected"
        evidence = inherited_evidence_for_issue(state, 24)
        self.assertNotIn("03-merge", [item["source_action_id"] for item in evidence])


if __name__ == "__main__":
    unittest.main()
