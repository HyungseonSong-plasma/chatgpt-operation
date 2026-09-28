import unittest

from chatgpt_operation.controller.action_plan import ActionPlan
from chatgpt_operation.controller.decisions import DecisionRegistry
from chatgpt_operation.controller.diagnostic import enqueue_suspended_action
from chatgpt_operation.controller.durable_state import encode_state
from chatgpt_operation.controller.issue_ingestion import encode_admission_ledger
from chatgpt_operation.controller.research import ResearchStage, ResearchState
from chatgpt_operation.controller.runtime import (
    ControllerTrigger,
    SamuelController,
    TriggerKind,
)


REPOSITORY="HyungseonSong-plasma/chatgpt-operation"
OLD_BRANCH="samuel/issues-24-43-weekly-maintenance-v2"
OLD_HEAD="f"*40
MAIN_HEAD="a"*40


def action(raw):
    return ActionPlan.from_dict(raw)


def state():
    current=ResearchState("issue:24","weekly",stage=ResearchStage.EXECUTE)
    create=action({
        "schema_version":1,"research_id":"issue:24","stage":"execute",
        "executor":"github_native",
        "payload":{
            "action":"create_pr","repository":REPOSITORY,
            "target":{"head":OLD_BRANCH,"base":"main","title":"weekly","body":"weekly"},
            "preconditions":{"pr_present":False},
            "desired_postcondition":{"pr_present":True},
        },
        "expected_observation":"PR exists",
    })
    merge=action({
        "schema_version":1,"research_id":"issue:24","stage":"execute",
        "executor":"github_native",
        "payload":{
            "action":"merge_pr","repository":REPOSITORY,
            "target":{"number":173,"expected_head_sha":OLD_HEAD},
            "desired_postcondition":{"merged":True},
        },
        "expected_observation":"PR merges",
    })
    for plan,status in ((create,"complete"),(merge,"rejected")):
        enqueue_suspended_action(current,plan)
        current.action_queue[plan.idempotency_key]["status"]=status
        current.action_queue[plan.idempotency_key]["completion_result"]={
            "schema_version":1,
            "research_id":"issue:24",
            "action_id":plan.idempotency_key,
            "executor":"github_native",
            "status":"pass" if status=="complete" else "rejected",
            "observation":"verified" if status=="complete" else "mergeable=false",
            "retryable":False,
            "details":{},
        }
    return current


def trigger():
    return ControllerTrigger(
        TriggerKind.WORKFLOW_DISPATCH,
        action="",
        head_sha=MAIN_HEAD,
        ref="refs/heads/main",
        executor_ref="main",
        executor_head_sha=MAIN_HEAD,
    )


def comments(current):
    ledger={
        "issue:24":{
            "work_id":"issue:24",
            "issue_number":24,
            "title":"Weekly maintenance",
            "body":"bounded weekly work",
            "html_url":"https://github.com/x/y/issues/24",
            "status":"planned",
        }
    }
    return [
        {"id":7,"body":encode_admission_ledger(ledger)},
        {"id":9,"body":encode_state(current)},
    ]


def repository_context():
    return {
        "repository":REPOSITORY,
        "observed_head_sha":MAIN_HEAD,
        "open_issues":[{
            "number":24,"title":"Weekly maintenance","body":"bounded weekly work",
            "state":"open","labels":["samuel"],
        }],
        "open_pull_requests":[{
            "number":173,"title":"weekly","state":"open","draft":False,
            "ci_state":"success","head_ref":OLD_BRANCH,"head_sha":OLD_HEAD,
            "base_ref":"main",
        }],
        "samuel_branches":[
            {"ref":"refs/heads/"+OLD_BRANCH,"head_sha":OLD_HEAD},
        ],
        "tracked_paths":[],
        "tracked_paths_truncated":False,
        "workflow_files":[".github/workflows/samuel-bootstrap.yml"],
    }


class MergeRecoveryRuntimeTests(unittest.TestCase):
    def test_rejected_merge_promotes_fresh_branch_not_same_merge(self):
        current=state()
        controller=SamuelController(
            decisions=DecisionRegistry.load("automation/samuel/decisions.json")
        )
        cycle=controller.run_cycle(
            trigger(),
            comments=comments(current),
            pending=[],
            repository_context=repository_context(),
        )
        self.assertEqual(cycle.selected_work["kind"],"action")
        plan=cycle.selected_work["plan"]
        self.assertEqual(plan["executor"],"repository_mutation")
        self.assertEqual(plan["payload"]["resource"],"branch")
        self.assertEqual(plan["payload"]["action"],"create")
        self.assertEqual(
            plan["payload"]["target"]["name"],
            "samuel/issue-24-refresh-"+MAIN_HEAD[:12],
        )
        self.assertEqual(plan["payload"]["desired"]["sha"],MAIN_HEAD)
        self.assertIsNotNone(cycle.execution_command)


if __name__=="__main__":
    unittest.main()
