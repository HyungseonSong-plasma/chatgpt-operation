import unittest

from chatgpt_operation.controller.action_plan import ActionPlan
from chatgpt_operation.controller.diagnostic import enqueue_suspended_action
from chatgpt_operation.controller.research import ResearchStage, ResearchState
from chatgpt_operation.controller.runtime import (
    _owned_pr_ci_plan,
    _owned_ready_pr_plan,
)


REPOSITORY="HyungseonSong-plasma/chatgpt-operation"
BRANCH="samuel/issues-24-43-weekly-maintenance-v2"
HEAD="f"*40


def state_with_owned_pr_action():
    state=ResearchState(
        "issue:24",
        "weekly maintenance",
        stage=ResearchStage.EXECUTE,
    )
    plan=ActionPlan.from_dict({
        "schema_version":1,
        "research_id":"issue:24",
        "stage":"execute",
        "executor":"github_native",
        "payload":{
            "action":"create_pr",
            "repository":REPOSITORY,
            "target":{
                "head":BRANCH,
                "base":"main",
                "title":"Weekly maintenance",
                "body":"bounded work",
            },
            "preconditions":{"pr_present":False},
            "desired_postcondition":{"pr_present":True},
        },
        "expected_observation":"PR exists",
    })
    enqueue_suspended_action(state,plan)
    action_id=plan.idempotency_key
    state.action_queue[action_id]["status"]="complete"
    state.execution_results[action_id]={
        "schema_version":1,
        "research_id":"issue:24",
        "action_id":action_id,
        "executor":"github_native",
        "status":"pass",
        "observation":"verified",
        "retryable":False,
        "details":{},
    }
    return state


def context(ci_state):
    return {
        "repository":REPOSITORY,
        "open_pull_requests":[{
            "number":173,
            "state":"open",
            "draft":False,
            "ci_state":ci_state,
            "head_ref":BRANCH,
            "head_sha":HEAD,
            "base_ref":"main",
        }],
    }


class OwnedPrCiLivenessTests(unittest.TestCase):
    def test_unknown_ci_promotes_exact_head_dispatch_before_merge(self):
        state=state_with_owned_pr_action()
        ci_plan=_owned_pr_ci_plan(state,context("unknown"))
        self.assertIsNotNone(ci_plan)
        self.assertEqual(ci_plan.payload["action"],"dispatch_workflow")
        self.assertEqual(
            ci_plan.payload["target"],
            {
                "workflow":"ci.yml",
                "ref":BRANCH,
                "expected_head_sha":HEAD,
            },
        )
        self.assertEqual(
            ci_plan.payload["preconditions"],
            {"head_sha":HEAD,"ci_started":False},
        )
        self.assertEqual(
            ci_plan.payload["desired_postcondition"],
            {"head_sha":HEAD,"ci_started":True},
        )
        self.assertIsNone(_owned_ready_pr_plan(state,context("unknown")))

    def test_pending_ci_does_not_redispatch_or_merge(self):
        state=state_with_owned_pr_action()
        self.assertIsNone(_owned_pr_ci_plan(state,context("pending")))
        self.assertIsNone(_owned_ready_pr_plan(state,context("pending")))

    def test_success_ci_skips_dispatch_and_promotes_exact_head_merge(self):
        state=state_with_owned_pr_action()
        self.assertIsNone(_owned_pr_ci_plan(state,context("success")))
        merge=_owned_ready_pr_plan(state,context("success"))
        self.assertIsNotNone(merge)
        self.assertEqual(merge.payload["action"],"merge_pr")
        self.assertEqual(merge.payload["target"]["number"],173)
        self.assertEqual(merge.payload["target"]["expected_head_sha"],HEAD)

    def test_failed_ci_neither_redispatches_nor_merges(self):
        state=state_with_owned_pr_action()
        self.assertIsNone(_owned_pr_ci_plan(state,context("failure")))
        self.assertIsNone(_owned_ready_pr_plan(state,context("failure")))


if __name__=="__main__":
    unittest.main()
