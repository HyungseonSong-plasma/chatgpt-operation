import unittest

from chatgpt_operation.controller.action_plan import ActionPlan
from chatgpt_operation.controller.decisions import DecisionRegistry
from chatgpt_operation.controller.diagnostic import enqueue_suspended_action
from chatgpt_operation.controller.durable_state import encode_state
from chatgpt_operation.controller.research import ResearchState
from chatgpt_operation.controller.issue_ingestion import (
    decode_admission_ledger,
    encode_admission_ledger,
)
from chatgpt_operation.controller.reasoning_provider import ReasoningProviderRegistry
from chatgpt_operation.controller.runtime import (
    ControllerTrigger,
    SamuelController,
    TriggerKind,
)


REPOSITORY="HyungseonSong-plasma/chatgpt-operation"
HEAD="a"*40
BRANCH="samuel/issue-24-preflight"
CRITERION="scheduler is durable"
BODY="""## Purpose

Weekly maintenance.

## Acceptance

- scheduler is durable
- retry handling is deterministic
"""


class RepairProvider:
    name="preflight-repair-fixture"

    def __init__(self):
        self.calls=0
        self.validation_errors=[]

    def reason(self,**kwargs):
        self.calls+=1
        self.validation_errors.append(kwargs.get("validation_error"))
        proposal={
            "operation":"analyze",
            "decision_id":"github_execution_authority",
            "compatible_with_locked_decisions":True,
            "revision_requested":False,
            "blocker":None,
            "action_plan":{
                "schema_version":1,
                "research_id":"issue:24",
                "stage":"implement",
                "executor":"repository_mutation",
                "payload":{
                    "schema_version":1,
                    "repository":REPOSITORY,
                    "resource":"file",
                    "action":"create",
                    "target":{
                        "path":"src/chatgpt_operation/preflight_probe.py",
                        "branch":BRANCH,
                    },
                    "expected":{"absent":True},
                    "desired":{"content":"READY=True\n"},
                    "commit_message":"Add preflight probe",
                },
                "expected_observation":"preflight probe exists",
            },
            "progress":None,
            "completion_claim":None,
        }
        if self.calls==2:
            proposal["progress"]={
                "criterion":CRITERION,
                "rationale":"the code-owned probe advances the durable scheduler criterion",
            }
        return proposal


def trigger():
    return ControllerTrigger(
        TriggerKind.WORKFLOW_DISPATCH,
        action="",
        head_sha=HEAD,
        ref="refs/heads/main",
        executor_ref="main",
        executor_head_sha=HEAD,
    )


def admission():
    return {
        "id":7,
        "body":encode_admission_ledger({
            "issue:24":{
                "work_id":"issue:24",
                "issue_number":24,
                "title":"Weekly maintenance",
                "body":BODY,
                "html_url":"https://github.com/HyungseonSong-plasma/chatgpt-operation/issues/24",
                "status":"reasoning_required",
            }
        }),
    }


def repository_context():
    return {
        "repository":REPOSITORY,
        "observed_head_sha":HEAD,
        "open_issues":[{
            "number":24,
            "title":"Weekly maintenance",
            "body":BODY,
            "state":"open",
            "labels":["samuel"],
        }],
        "open_pull_requests":[],
        "samuel_branches":[{
            "ref":"refs/heads/"+BRANCH,
            "head_sha":"b"*40,
        }],
        "tracked_paths":["src/chatgpt_operation/weekly_maintenance.py"],
        "tracked_paths_truncated":False,
        "workflow_files":[".github/workflows/samuel-bootstrap.yml"],
    }


def integrated_state_comment():
    state=ResearchState("issue:24","weekly maintenance")
    plans=[
        (
            {
                "schema_version":1,
                "research_id":"issue:24",
                "stage":"implement",
                "executor":"repository_mutation",
                "payload":{
                    "schema_version":1,
                    "repository":REPOSITORY,
                    "resource":"file",
                    "action":"create",
                    "target":{
                        "path":"src/chatgpt_operation/integrated_probe.py",
                        "branch":BRANCH,
                    },
                    "expected":{"absent":True},
                    "desired":{"content":"READY=True\n"},
                    "commit_message":"Add integrated probe",
                },
                "expected_observation":"integrated probe exists",
            },
            {"criterion":CRITERION,"rationale":"merged criterion evidence"},
            {},
        ),
        (
            {
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
                        "title":"bounded acceptance work",
                        "body":"bounded acceptance work",
                    },
                    "preconditions":{"pr_present":False},
                    "desired_postcondition":{"pr_present":True},
                },
                "expected_observation":"reviewable PR exists",
            },
            None,
            {"after":{"pr_number":99,"head_sha":"c"*40}},
        ),
        (
            {
                "schema_version":1,
                "research_id":"issue:24",
                "stage":"execute",
                "executor":"github_native",
                "payload":{
                    "action":"merge_pr",
                    "repository":REPOSITORY,
                    "target":{"number":99,"expected_head_sha":"c"*40},
                    "desired_postcondition":{"merged":True},
                },
                "expected_observation":"reviewed PR is merged",
            },
            None,
            {"after":{"merged":True,"head_sha":"c"*40}},
        ),
    ]
    for raw,progress,details in plans:
        plan=ActionPlan.from_dict(raw)
        enqueue_suspended_action(state,plan)
        action_id=plan.idempotency_key
        state.action_queue[action_id]["status"]="complete"
        state.action_queue[action_id]["completion_result"]={
            "schema_version":1,
            "research_id":"issue:24",
            "action_id":action_id,
            "executor":plan.executor.value,
            "status":"pass",
            "observation":"verified",
            "retryable":False,
            "details":details,
        }
        if progress is not None:
            state.action_queue[action_id]["progress"]=progress
    return {"id":8,"body":encode_state(state)}


class EligibleCriterionProvider:
    name="eligible-criterion-fixture"

    def __init__(self):
        self.calls=0
        self.context=None

    def reason(self,**kwargs):
        self.calls+=1
        self.context=kwargs["context"]
        eligible=self.context["eligible_acceptance_criteria"]
        if eligible != ["retry handling is deterministic"]:
            raise AssertionError("provider must receive only unfinished acceptance work")
        return {
            "operation":"analyze",
            "decision_id":"github_execution_authority",
            "compatible_with_locked_decisions":True,
            "revision_requested":False,
            "blocker":None,
            "action_plan":{
                "schema_version":1,
                "research_id":"issue:24",
                "stage":"implement",
                "executor":"repository_mutation",
                "payload":{
                    "schema_version":1,
                    "repository":REPOSITORY,
                    "resource":"file",
                    "action":"create",
                    "target":{
                        "path":"src/chatgpt_operation/eligible_probe.py",
                        "branch":BRANCH,
                    },
                    "expected":{"absent":True},
                    "desired":{"content":"READY=True\n"},
                    "commit_message":"Add eligible acceptance probe",
                },
                "expected_observation":"eligible acceptance probe exists",
            },
            "progress":{
                "criterion":eligible[0],
                "rationale":"advances only controller-eligible acceptance work",
            },
            "completion_claim":None,
        }


class DecisionRepairProvider:
    name="decision-repair-fixture"

    def __init__(self):
        self.calls=0
        self.validation_errors=[]

    def reason(self,**kwargs):
        self.calls+=1
        self.validation_errors.append(kwargs.get("validation_error"))
        return {
            "operation":"analyze",
            "decision_id":(
                "issue:24"
                if self.calls==1
                else "github_execution_authority"
            ),
            "compatible_with_locked_decisions":True,
            "revision_requested":False,
            "blocker":None,
            "action_plan":{
                "schema_version":1,
                "research_id":"issue:24",
                "stage":"implement",
                "executor":"repository_mutation",
                "payload":{
                    "schema_version":1,
                    "repository":REPOSITORY,
                    "resource":"file",
                    "action":"create",
                    "target":{
                        "path":"src/chatgpt_operation/decision_probe.py",
                        "branch":BRANCH,
                    },
                    "expected":{"absent":True},
                    "desired":{"content":"READY=True\n"},
                    "commit_message":"Add decision repair probe",
                },
                "expected_observation":"decision repair probe exists",
            },
            "progress":{
                "criterion":CRITERION,
                "rationale":"advances the durable scheduler criterion",
            },
            "completion_claim":None,
        }


class SemanticPreflightRuntimeTests(unittest.TestCase):
    def test_reasoning_receives_only_controller_eligible_acceptance_criteria(self):
        provider=EligibleCriterionProvider()
        controller=SamuelController(
            decisions=DecisionRegistry.load("automation/samuel/decisions.json"),
            reasoning=ReasoningProviderRegistry(provider),
        )
        cycle=controller.run_cycle(
            trigger(),
            comments=[admission(),integrated_state_comment()],
            pending=[],
            repository_context=repository_context(),
        )
        self.assertEqual(provider.calls,1)
        self.assertEqual(
            provider.context["acceptance_criteria"],
            ["retry handling is deterministic"],
        )
        self.assertEqual(
            provider.context["eligible_acceptance_criteria"],
            ["retry handling is deterministic"],
        )
        self.assertIn(
            CRITERION,
            provider.context["durable_state"]["integrated_acceptance_evidence"],
        )
        self.assertEqual(cycle.selected_work["kind"],"action")
        self.assertEqual(
            cycle.issue_planning["proposal"]["progress"]["criterion"],
            "retry handling is deterministic",
        )

    def test_invalid_non_null_decision_id_repairs_inside_same_cycle(self):
        provider=DecisionRepairProvider()
        controller=SamuelController(
            decisions=DecisionRegistry.load("automation/samuel/decisions.json"),
            reasoning=ReasoningProviderRegistry(provider),
        )
        cycle=controller.run_cycle(
            trigger(),
            comments=[admission()],
            pending=[],
            repository_context=repository_context(),
        )
        self.assertEqual(provider.calls,2)
        self.assertIsNone(provider.validation_errors[0])
        self.assertIn(
            "decision_id must be null or reference an existing locked decision",
            provider.validation_errors[1],
        )
        self.assertEqual(cycle.selected_work["kind"],"action")
        self.assertEqual(
            cycle.issue_planning["proposal"]["decision_id"],
            "github_execution_authority",
        )

    def test_preflight_failure_repairs_inside_same_reasoning_cycle(self):
        provider=RepairProvider()
        controller=SamuelController(
            decisions=DecisionRegistry.load("automation/samuel/decisions.json"),
            reasoning=ReasoningProviderRegistry(provider),
        )
        cycle=controller.run_cycle(
            trigger(),
            comments=[admission()],
            pending=[],
            repository_context=repository_context(),
        )
        self.assertEqual(provider.calls,2)
        self.assertIsNone(provider.validation_errors[0])
        self.assertIn("PREFLIGHT_REJECTED",provider.validation_errors[1])
        self.assertIn("missing_acceptance_progress",provider.validation_errors[1])
        self.assertEqual(cycle.selected_work["kind"],"action")
        self.assertEqual(
            cycle.selected_work["plan"]["payload"]["target"]["path"],
            "src/chatgpt_operation/preflight_probe.py",
        )
        state_write=cycle.state_write
        self.assertIsNotNone(state_write)
        ledger=decode_admission_ledger(cycle.admission_write["body"])
        self.assertEqual(ledger["issue:24"]["status"],"planned")
        action_id=cycle.selected_work["action_id"]
        from chatgpt_operation.controller.durable_state import decode_state
        proposed=decode_state(state_write["body"])
        self.assertEqual(
            proposed.action_queue[action_id]["progress"]["criterion"],
            CRITERION,
        )


if __name__=="__main__":
    unittest.main()
