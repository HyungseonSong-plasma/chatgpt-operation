import unittest

from chatgpt_operation.controller.action_plan import ActionPlan
from chatgpt_operation.controller.bootstrap import BootstrapKind, BootstrapWork
from chatgpt_operation.controller.diagnostic import enqueue_suspended_action
from chatgpt_operation.controller.durable_state import decode_state, encode_state
from chatgpt_operation.controller.research import ResearchStage, ResearchState
from chatgpt_operation.controller.decisions import DecisionRegistry
from chatgpt_operation.controller.issue_ingestion import (
    decode_admission_ledger,
    encode_admission_ledger,
)
from chatgpt_operation.controller.issue_reasoning import IssueReasoningProposal
from chatgpt_operation.controller.reasoning_provider import ReasoningProviderRegistry
from chatgpt_operation.controller.reasoning_submission import (
    ReasoningSubmission,
    encode_submission,
)
from chatgpt_operation.controller.runtime import (
    ControllerCompositionError,
    ControllerTrigger,
    SamuelController,
    TriggerKind,
)


class Provider:
    name = "fixture"
    def __init__(self):
        self.calls = 0
    def reason(self, **kwargs):
        self.calls += 1
        raise AssertionError("composition preflight must not invoke semantic provider")


def controller(reasoning=None, now=None):
    return SamuelController(
        decisions=DecisionRegistry.load("automation/samuel/decisions.json"),
        reasoning=reasoning,
        now=now,
    )


def trigger():
    return ControllerTrigger(
        TriggerKind.WORKFLOW_DISPATCH,
        action="",
        head_sha="a"*40,
        ref="refs/heads/main",
        executor_ref="main",
        executor_head_sha="b"*40,
    )


def admitted_comment(status="admitted"):
    work={
        "issue:44":{
            "work_id":"issue:44",
            "issue_number":44,
            "title":"Samuel OS",
            "body":"finish controller composition",
            "html_url":"https://github.com/o/r/issues/44",
            "status":status,
        }
    }
    return {"id":7,"body":encode_admission_ledger(work)}


def reasoning_comment(action_plan=None):
    proposal=IssueReasoningProposal(
        operation="analyze",
        decision_id="github_execution_authority",
        compatible_with_locked_decisions=True,
        revision_requested=False,
        action_plan=action_plan,
    )
    return {
        "id":8,
        "body":encode_submission(ReasoningSubmission("issue:44",proposal)),
    }


def state_comment(state):
    return {"id":9,"body":encode_state(state)}


def queued_state():
    plan=ActionPlan.from_dict(native_action_plan())
    state=ResearchState(
        "issue:44","execute queued work",stage=ResearchStage.EXECUTE
    )
    enqueue_suspended_action(state,plan)
    return plan,state


def native_action_plan():
    return {
        "schema_version":1,
        "research_id":"issue:44",
        "stage":"implement",
        "executor":"github_native",
        "payload":{
            "action":"comment_issue",
            "repository":"HyungseonSong-plasma/chatgpt-operation",
            "target":{
                "number":44,
                "body":"<!-- composition-root-test -->",
                "marker":"<!-- composition-root-test -->",
            },
            "preconditions":{"issue_state":"open","comment_present":False},
            "desired_postcondition":{"comment_present":True},
        },
        "expected_observation":"Issue #44 contains composition-root-test marker",
    }


class ControllerRuntimeTests(unittest.TestCase):
    def test_idle_cycle_has_one_typed_root_result(self):
        result=controller().run_cycle(trigger(),comments=[],pending=[])
        self.assertEqual(result.selected_work,{"kind":"idle"})
        self.assertIsNone(result.issue_planning)
        self.assertIsNone(result.admission_write)
        self.assertIsNone(result.state_write)
        self.assertEqual(result.to_dict()["schema_version"],2)

    def test_admitted_issue_builds_reasoning_preflight_and_transition(self):
        result=controller().run_cycle(
            trigger(),comments=[admitted_comment()],pending=[]
        )
        self.assertEqual(result.selected_work,{
            "kind":"reasoning_required","work_id":"issue:44"
        })
        planning=result.issue_planning
        self.assertIsNotNone(planning)
        self.assertEqual(planning["outcome"],"reasoning_required")
        self.assertIsNone(planning["action_plan"])
        self.assertTrue(planning["reasoning_context"]["locked_decisions"])
        self.assertIn("typed_proposal",planning["reasoning_context"]["required_outputs"])
        self.assertIsNotNone(result.admission_write)
        persisted=decode_admission_ledger(result.admission_write["body"])
        self.assertEqual(persisted["issue:44"]["status"],"reasoning_required")
        self.assertIsNone(result.state_write)

    def test_available_provider_is_observed_but_not_invoked_in_preflight(self):
        provider=Provider()
        result=controller(ReasoningProviderRegistry(provider)).run_cycle(
            trigger(),comments=[admitted_comment()],pending=[]
        )
        self.assertEqual(provider.calls,0)
        self.assertTrue(result.issue_planning["semantic_provider"]["available"])
        self.assertEqual(result.issue_planning["semantic_provider"]["provider"],"fixture")
        self.assertEqual(result.issue_planning["outcome"],"reasoning_required")

    def test_existing_submission_is_consumed_in_same_root_cycle(self):
        result=controller().run_cycle(
            trigger(),
            comments=[admitted_comment(),reasoning_comment(native_action_plan())],
            pending=[],
        )
        self.assertEqual(result.selected_work["kind"],"action")
        self.assertEqual(result.selected_work["reasoning_outcome"],"planned")
        self.assertIsNotNone(result.selected_work["action_id"])
        self.assertIsNotNone(result.admission_write)
        persisted=decode_admission_ledger(result.admission_write["body"])
        self.assertEqual(persisted["issue:44"]["status"],"planned")
        self.assertIsNotNone(result.state_write)
        self.assertEqual(result.state_write["research_id"],"issue:44")
        self.assertEqual(result.state_write["expected_revision"],2)
        proposed=decode_state(result.state_write["body"])
        item=proposed.action_queue[result.selected_work["action_id"]]
        self.assertEqual(item["status"],"dispatch_intent")

    def test_analyze_only_submission_remains_reasoning_required(self):
        result=controller().run_cycle(
            trigger(),
            comments=[admitted_comment(),reasoning_comment()],
            pending=[],
        )
        self.assertEqual(result.selected_work["kind"],"reasoning_required")
        self.assertIsNotNone(result.admission_write)
        self.assertIsNone(result.state_write)

    def test_preexisting_reasoning_required_without_submission_waits(self):
        result=controller().run_cycle(
            trigger(),comments=[admitted_comment("reasoning_required")],pending=[]
        )
        self.assertEqual(result.selected_work,{
            "kind":"reasoning_required","work_id":"issue:44"
        })
        self.assertIsNone(result.admission_write)
        self.assertIsNone(result.state_write)

    def test_pending_action_is_promoted_to_dispatch_intent_by_root(self):
        plan,state=queued_state()
        result=controller(now=lambda: __import__("datetime").datetime(
            2026,9,27,19,0,tzinfo=__import__("datetime").timezone.utc
        )).run_cycle(
            trigger(),comments=[state_comment(state)],pending=[]
        )
        self.assertEqual(result.selected_work["kind"],"action")
        self.assertEqual(result.selected_work["action_id"],plan.idempotency_key)
        self.assertIsNotNone(result.state_write)
        proposed=decode_state(result.state_write["body"])
        item=proposed.action_queue[plan.idempotency_key]
        self.assertEqual(item["status"],"dispatch_intent")
        self.assertEqual(item["dispatch_intent"]["ref"],"main")
        self.assertEqual(item["dispatch_intent"]["expected_head_sha"],"b"*40)

    def test_evidence_work_is_promoted_to_dispatch_intent_by_root(self):
        action_id="c"*64
        state=ResearchState(
            "issue:44","acquire evidence",stage=ResearchStage.EXECUTE,
            diagnostic_recoveries={
                action_id:{
                    "status":"needs_evidence",
                    "evidence_request":{"fingerprint":"evidence-fingerprint"},
                }
            },
        )
        result=controller().run_cycle(
            trigger(),comments=[state_comment(state)],pending=[]
        )
        self.assertEqual(result.selected_work["kind"],"evidence")
        proposed=decode_state(result.state_write["body"])
        dispatch=proposed.diagnostic_recoveries[action_id]["evidence_dispatch"]
        self.assertEqual(dispatch["status"],"dispatch_intent")
        self.assertEqual(dispatch["intent"]["expected_head_sha"],"b"*40)

    def test_diagnostic_work_is_promoted_to_dispatch_intent_by_root(self):
        action_id="d"*64
        state=ResearchState(
            "issue:44","diagnose",stage=ResearchStage.EXECUTE,
            diagnostic_recoveries={
                action_id:{
                    "status":"open",
                    "fingerprint":["failure"],
                    "failure":{"details":{"provider":"native","error_type":"HTTPError"}},
                    "root_cause":None,
                    "corrective_action":None,
                    "resolution_evidence":None,
                }
            },
        )
        result=controller().run_cycle(
            trigger(),comments=[state_comment(state)],pending=[]
        )
        self.assertEqual(result.selected_work["kind"],"diagnostic")
        proposed=decode_state(result.state_write["body"])
        dispatch=proposed.diagnostic_recoveries[action_id]["diagnostic_dispatch"]
        self.assertEqual(dispatch["status"],"dispatch_intent")
        self.assertEqual(dispatch["intent"]["expected_head_sha"],"b"*40)

    def test_dispatchable_work_requires_executor_identity(self):
        plan,state=queued_state()
        missing=ControllerTrigger(
            TriggerKind.WORKFLOW_DISPATCH,
            head_sha="a"*40,
            ref="refs/heads/main",
        )
        with self.assertRaisesRegex(ControllerCompositionError,"executor_ref"):
            controller().run_cycle(
                missing,comments=[state_comment(state)],pending=[]
            )

    def test_pending_work_is_serialized_by_root(self):
        work=BootstrapWork(
            "legacy",BootstrapKind.WORKFLOW,"qualification.yml",ref="main"
        )
        result=controller().run_cycle(trigger(),comments=[],pending=[work])
        self.assertEqual(result.selected_work,{
            "kind":"pending",
            "work_id":"legacy",
            "workflow":"qualification.yml",
            "ref":"main",
        })

    def test_partial_planned_commit_without_state_recovers_to_reasoning_required(self):
        result=controller().run_cycle(
            trigger(),comments=[admitted_comment("planned")],pending=[]
        )
        self.assertEqual(result.selected_work["kind"],"reasoning_required")
        self.assertIsNotNone(result.admission_write)
        persisted=decode_admission_ledger(result.admission_write["body"])
        self.assertEqual(persisted["issue:44"]["status"],"reasoning_required")

    def test_multiple_admission_ledgers_fail_closed(self):
        comments=[admitted_comment(),{"id":8,"body":admitted_comment()["body"]}]
        with self.assertRaisesRegex(ControllerCompositionError,"multiple admission ledgers"):
            controller().run_cycle(trigger(),comments=comments,pending=[])

    def test_trigger_schema_fails_closed(self):
        with self.assertRaisesRegex(ControllerCompositionError,"unsupported"):
            ControllerTrigger.from_dict({
                "kind":"invented","action":"","head_sha":"","ref":"",
                "executor_ref":"","executor_head_sha":"",
            })


if __name__=="__main__":
    unittest.main()
