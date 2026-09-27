import unittest

from chatgpt_operation.controller.bootstrap import BootstrapKind, BootstrapWork
from chatgpt_operation.controller.decisions import DecisionRegistry
from chatgpt_operation.controller.issue_ingestion import encode_admission_ledger
from chatgpt_operation.controller.reasoning_provider import ReasoningProviderRegistry
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


def controller(reasoning=None):
    return SamuelController(
        decisions=DecisionRegistry.load("automation/samuel/decisions.json"),
        reasoning=reasoning,
    )


def trigger():
    return ControllerTrigger(
        TriggerKind.WORKFLOW_DISPATCH,
        action="",
        head_sha="a"*40,
        ref="refs/heads/main",
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


class ControllerRuntimeTests(unittest.TestCase):
    def test_idle_cycle_has_one_typed_root_result(self):
        result=controller().run_cycle(trigger(),comments=[],pending=[])
        self.assertEqual(result.selected_work,{"kind":"idle"})
        self.assertIsNone(result.issue_planning)
        self.assertEqual(result.to_dict()["schema_version"],1)

    def test_admitted_issue_builds_reasoning_preflight(self):
        result=controller().run_cycle(
            trigger(),comments=[admitted_comment()],pending=[]
        )
        self.assertEqual(result.selected_work["kind"],"issue")
        planning=result.issue_planning
        self.assertIsNotNone(planning)
        self.assertEqual(planning["outcome"],"reasoning_required")
        self.assertIsNone(planning["action_plan"])
        self.assertTrue(planning["reasoning_context"]["locked_decisions"])
        self.assertIn("typed_proposal",planning["reasoning_context"]["required_outputs"])

    def test_available_provider_is_observed_but_not_invoked_in_preflight(self):
        provider=Provider()
        result=controller(ReasoningProviderRegistry(provider)).run_cycle(
            trigger(),comments=[admitted_comment()],pending=[]
        )
        self.assertEqual(provider.calls,0)
        self.assertTrue(result.issue_planning["semantic_provider"]["available"])
        self.assertEqual(result.issue_planning["semantic_provider"]["provider"],"fixture")
        self.assertEqual(result.issue_planning["outcome"],"reasoning_required")

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

    def test_multiple_admission_ledgers_fail_closed(self):
        comments=[admitted_comment(),{"id":8,"body":admitted_comment()["body"]}]
        with self.assertRaisesRegex(ControllerCompositionError,"multiple admission ledgers"):
            controller().run_cycle(trigger(),comments=comments,pending=[])

    def test_trigger_schema_fails_closed(self):
        with self.assertRaisesRegex(ControllerCompositionError,"unsupported"):
            ControllerTrigger.from_dict({
                "kind":"invented","action":"","head_sha":"","ref":"",
            })


if __name__=="__main__":
    unittest.main()
