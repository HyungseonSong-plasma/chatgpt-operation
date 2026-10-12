import copy
import unittest

from chatgpt_operation.controller.decisions import DecisionRegistry
from chatgpt_operation.controller.durable_state import decode_state, encode_state
from chatgpt_operation.controller.issue_ingestion import encode_admission_ledger
from chatgpt_operation.controller.predispatch_recovery import (
    classify_predispatch_failure,
    record_predispatch_failure,
    resolve_predispatch_failure,
    unresolved_predispatch_failure,
)
from chatgpt_operation.controller.reasoning_provider import ReasoningProviderRegistry
from chatgpt_operation.controller.research import ResearchState
from chatgpt_operation.controller.runtime import (
    ControllerTrigger,
    SamuelController,
    TriggerKind,
)


REPOSITORY = "HyungseonSong-plasma/chatgpt-operation"
HEAD = "a" * 40
CRITERION = "controller recovery is durable"
BODY = f"""## Goal

Exercise bounded planning recovery.

## Acceptance

- {CRITERION}
"""


class InvalidPlanningProvider:
    name = "invalid-planning-fixture"

    def __init__(self):
        self.calls = 0

    def reason(self, **kwargs):
        self.calls += 1
        return {
            "operation": "implement_gap",
            "decision_id": None,
            "compatible_with_locked_decisions": True,
            "revision_requested": False,
            "blocker": None,
            "action_plan": None,
            "progress": None,
            "completion_claim": None,
        }


def trigger():
    return ControllerTrigger(
        TriggerKind.WORKFLOW_DISPATCH,
        head_sha=HEAD,
        ref="refs/heads/main",
        executor_ref="main",
        executor_head_sha=HEAD,
    )


def admission():
    return {
        "id": 7,
        "body": encode_admission_ledger({
            "issue:211": {
                "work_id": "issue:211",
                "issue_number": 211,
                "title": "pre-dispatch recovery",
                "body": BODY,
                "html_url": "https://github.com/o/r/issues/211",
                "status": "reasoning_required",
            }
        }),
    }


def repository_context():
    return {
        "repository": REPOSITORY,
        "observed_head_sha": HEAD,
        "open_issues": [{
            "number": 211,
            "title": "pre-dispatch recovery",
            "body": BODY,
            "state": "open",
            "labels": ["samuel"],
        }],
        "open_issues_complete": True,
        "open_pull_requests": [],
        "samuel_branches": ["samuel/issue-211-predispatch-recovery"],
        "tracked_paths": [],
        "tracked_paths_truncated": False,
        "workflow_files": [".github/workflows/samuel-bootstrap.yml"],
    }


class PredispatchRecoveryTests(unittest.TestCase):
    def test_first_failure_is_retryable_and_identical_recurrence_escalates(self):
        state = ResearchState("issue:211", "test")
        first = record_predispatch_failure(
            state,
            work_id="issue:211",
            target_acceptance_criterion=CRITERION,
            error="implement_gap is invalid because implementation_gaps is empty",
            node_attempts=2,
            repository_context=repository_context(),
        )
        self.assertEqual(first["failure_class"], "planning_validation")
        self.assertEqual(first["status"], "retryable")
        self.assertEqual(first["branch_identity"], "samuel/issue-211-predispatch-recovery")
        first_revision = state.revision

        second = record_predispatch_failure(
            state,
            work_id="issue:211",
            target_acceptance_criterion=CRITERION,
            error="implement_gap is invalid because implementation_gaps is empty",
            node_attempts=2,
            repository_context=repository_context(),
        )
        self.assertEqual(second["status"], "escalated")
        self.assertEqual(second["occurrences"], 2)
        self.assertEqual(state.revision, first_revision + 1)

    def test_authority_policy_failure_is_blocked_without_retry(self):
        state = ResearchState("issue:211", "test")
        record = record_predispatch_failure(
            state,
            work_id="issue:211",
            target_acceptance_criterion=CRITERION,
            error="repository mutation policy rejected ActionPlan: path denied",
            node_attempts=2,
            repository_context=repository_context(),
        )
        self.assertEqual(record["failure_class"], "authority_policy")
        self.assertEqual(record["status"], "blocked")

    def test_successful_reasoning_resolution_is_auditable(self):
        state = ResearchState("issue:211", "test")
        record = record_predispatch_failure(
            state,
            work_id="issue:211",
            target_acceptance_criterion=CRITERION,
            error="typed schema mismatch",
            node_attempts=2,
            repository_context=repository_context(),
        )
        fingerprint = record["fingerprint"]
        resolved = resolve_predispatch_failure(state, CRITERION)
        self.assertEqual(resolved, (fingerprint,))
        self.assertEqual(state.predispatch_failures[fingerprint]["status"], "resolved")
        self.assertIsNone(unresolved_predispatch_failure(state, CRITERION))

    def test_capability_claim_is_not_promoted_to_proven_exhaustion(self):
        self.assertEqual(
            classify_predispatch_failure(
                "capability is exhausted because the connector action is unavailable"
            ),
            "reasoning_validation",
        )

    def test_runtime_persists_failure_then_escalates_same_fingerprint(self):
        provider = InvalidPlanningProvider()
        controller = SamuelController(
            decisions=DecisionRegistry.load("automation/samuel/decisions.json"),
            reasoning=ReasoningProviderRegistry(provider),
            reasoning_enabled=True,
        )
        first = controller.run_cycle(
            trigger(),
            comments=[admission()],
            pending=[],
            repository_context=repository_context(),
        )
        self.assertEqual(first.selected_work["kind"], "controller_recovery")
        self.assertIsNotNone(first.state_write)
        self.assertIsNone(first.execution_command)
        first_state = decode_state(first.state_write["body"])
        first_failure = unresolved_predispatch_failure(first_state, CRITERION)
        self.assertEqual(first_failure["status"], "retryable")
        self.assertEqual(provider.calls, 2)

        comments = [admission(), {"id": 8, "body": first.state_write["body"]}]
        second = controller.run_cycle(
            trigger(),
            comments=comments,
            pending=[],
            repository_context=repository_context(),
        )
        self.assertEqual(second.selected_work["kind"], "controller_escalated")
        self.assertIsNotNone(second.state_write)
        second_state = decode_state(second.state_write["body"])
        second_failure = unresolved_predispatch_failure(second_state, CRITERION)
        self.assertEqual(second_failure["status"], "escalated")
        self.assertEqual(provider.calls, 4)

        third = controller.run_cycle(
            trigger(),
            comments=[admission(), {"id": 8, "body": second.state_write["body"]}],
            pending=[],
            repository_context=repository_context(),
        )
        self.assertEqual(third.selected_work["kind"], "controller_escalated")
        self.assertIsNone(third.state_write)
        self.assertEqual(provider.calls, 4)

    def test_durable_round_trip_preserves_predispatch_failure(self):
        state = ResearchState("issue:211", "test")
        record_predispatch_failure(
            state,
            work_id="issue:211",
            target_acceptance_criterion=CRITERION,
            error="typed schema mismatch",
            node_attempts=2,
            repository_context=repository_context(),
        )
        restored = decode_state(encode_state(state))
        self.assertEqual(restored.predispatch_failures, state.predispatch_failures)


if __name__ == "__main__":
    unittest.main()
