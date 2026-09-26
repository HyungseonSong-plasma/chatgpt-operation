import unittest

from chatgpt_operation.controller.action_plan import ActionPlan
from chatgpt_operation.controller.execution import ExecutionStatus
from chatgpt_operation.github.native_executor import NativeGitHubError, execute_native_github


def plan(action="merge_pr"):
    return ActionPlan.from_dict({
        "schema_version": 1,
        "research_id": "samuel-44",
        "stage": "execute",
        "executor": "github_native",
        "payload": {
            "action": action,
            "repository": "HyungseonSong-plasma/chatgpt-operation",
            "target": {"number": 42},
            "preconditions": {"head_sha": "abc", "mergeable": True, "ci": "success"},
            "desired_postcondition": {"merged": True},
        },
        "expected_observation": "merged",
    })


class NativeGitHubExecutorTests(unittest.TestCase):
    def test_replay_is_noop_when_postcondition_already_holds(self):
        result = execute_native_github(
            plan(),
            read_state=lambda action, target: {"merged": True},
            mutate=lambda action, target: self.fail("must not mutate"),
        )
        self.assertEqual(result.status, ExecutionStatus.NOOP)

    def test_stale_head_rejects_without_mutation(self):
        result = execute_native_github(
            plan(),
            read_state=lambda action, target: {"merged": False, "head_sha": "new", "mergeable": True, "ci": "success"},
            mutate=lambda action, target: self.fail("must not mutate"),
        )
        self.assertEqual(result.status, ExecutionStatus.REJECTED)

    def test_mutation_requires_postcondition_readback(self):
        states = iter([
            {"merged": False, "head_sha": "abc", "mergeable": True, "ci": "success"},
            {"merged": True, "head_sha": "abc"},
        ])
        result = execute_native_github(
            plan(),
            read_state=lambda action, target: next(states),
            mutate=lambda action, target: {"merge_sha": "def"},
        )
        self.assertEqual(result.status, ExecutionStatus.PASS)
        self.assertEqual(result.details["after"]["merged"], True)

    def test_failed_postcondition_is_retryable_failure(self):
        states = iter([
            {"merged": False, "head_sha": "abc", "mergeable": True, "ci": "success"},
            {"merged": False, "head_sha": "abc"},
        ])
        result = execute_native_github(
            plan(),
            read_state=lambda action, target: next(states),
            mutate=lambda action, target: {"accepted": True},
        )
        self.assertEqual(result.status, ExecutionStatus.FAILED)
        self.assertTrue(result.retryable)

    def test_unknown_action_fails_closed(self):
        with self.assertRaises(NativeGitHubError):
            plan("delete_repository")


if __name__ == "__main__":
    unittest.main()
