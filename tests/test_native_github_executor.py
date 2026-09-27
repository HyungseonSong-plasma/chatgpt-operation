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
            "target": {"number": 42, "expected_head_sha": "a"*40},
            "preconditions": {"head_sha": "a"*40, "mergeable": True, "ci": "success"},
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
            {"merged": False, "head_sha": "a"*40, "mergeable": True, "ci": "success"},
            {"merged": True, "head_sha": "a"*40},
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
            {"merged": False, "head_sha": "a"*40, "mergeable": True, "ci": "success"},
            {"merged": False, "head_sha": "a"*40},
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
            execute_native_github(
                plan("delete_repository"),
                read_state=lambda action, target: self.fail("must not read state"),
                mutate=lambda action, target: self.fail("must not mutate"),
            )


if __name__ == "__main__":
    unittest.main()


def create_pr_plan(**target_changes):
    target={
        "head":"samuel/issues-24-43",
        "base":"main",
        "title":"Implement telemetry maintenance",
        "body":"Closes #24 and #43",
    }
    target.update(target_changes)
    return ActionPlan.from_dict({
        "schema_version":1,
        "research_id":"samuel-44",
        "stage":"implement",
        "executor":"github_native",
        "payload":{
            "action":"create_pr",
            "repository":"HyungseonSong-plasma/chatgpt-operation",
            "target":target,
            "preconditions":{"pr_present":False},
            "desired_postcondition":{"pr_present":True},
        },
        "expected_observation":"open PR exists for the exact head/base",
    })


def test_create_pr_is_idempotent_through_postcondition():
    result=execute_native_github(
        create_pr_plan(),
        read_state=lambda action,target:{"pr_present":True,"pr_number":130},
        mutate=lambda action,target: (_ for _ in ()).throw(
            AssertionError("must not duplicate PR")
        ),
    )
    assert result.status is ExecutionStatus.NOOP


def test_create_pr_target_schema_is_closed_world():
    try:
        execute_native_github(
            create_pr_plan(extra="not-allowed"),
            read_state=lambda action,target:{},
            mutate=lambda action,target:{},
        )
    except NativeGitHubError as exc:
        assert "head, base, title, and body" in str(exc)
    else:
        raise AssertionError("unexpected create_pr target field must fail closed")


def test_merge_pr_derives_mandatory_safety_preconditions():
    p=ActionPlan.from_dict({
        "schema_version":1,
        "research_id":"samuel-44",
        "stage":"execute",
        "executor":"github_native",
        "payload":{
            "action":"merge_pr",
            "repository":"HyungseonSong-plasma/chatgpt-operation",
            "target":{
                "number":136,
                "expected_head_sha":"c"*40,
            },
            "desired_postcondition":{"merged":True},
        },
        "expected_observation":"PR merged at exact verified head",
    })
    seen=[]
    result=execute_native_github(
        p,
        read_state=lambda action,target: {
            "merged":False,
            "head_sha":"c"*40,
            "mergeable":True,
            "ci":"pending",
        },
        mutate=lambda action,target: seen.append(target) or {"merged":True},
    )
    assert result.status is ExecutionStatus.REJECTED
    assert not seen
    assert result.details["required"] == {
        "head_sha":"c"*40,
        "mergeable":True,
        "ci":"success",
    }


def test_merge_pr_rejects_weaker_reasoning_precondition():
    p=ActionPlan.from_dict({
        "schema_version":1,
        "research_id":"samuel-44",
        "stage":"execute",
        "executor":"github_native",
        "payload":{
            "action":"merge_pr",
            "repository":"HyungseonSong-plasma/chatgpt-operation",
            "target":{
                "number":136,
                "expected_head_sha":"c"*40,
            },
            "preconditions":{"ci":"pending"},
            "desired_postcondition":{"merged":True},
        },
        "expected_observation":"PR merged",
    })
    try:
        execute_native_github(
            p,
            read_state=lambda action,target: {},
            mutate=lambda action,target: {},
        )
    except NativeGitHubError as exc:
        assert "mandatory safety gate" in str(exc)
    else:
        raise AssertionError("reasoning may not weaken merge safety gates")
