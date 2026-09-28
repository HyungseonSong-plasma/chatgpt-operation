import unittest

from chatgpt_operation.controller.action_plan import ActionPlan
from chatgpt_operation.controller.bootstrap import BootstrapKind, BootstrapWork
from chatgpt_operation.controller.command import ControllerCommandKind
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
        self.context = None
    def reason(self, **kwargs):
        self.calls += 1
        self.context = kwargs["context"]
        return {
            "operation":"analyze",
            "decision_id":"github_execution_authority",
            "compatible_with_locked_decisions":True,
            "revision_requested":False,
            "action_plan":native_action_plan(),
        }




class StaticPlanProvider:
    name = "static-plan-fixture"

    def __init__(self, plan):
        self.plan = plan
        self.calls = 0

    def reason(self, **kwargs):
        self.calls += 1
        return {
            "operation":"analyze",
            "decision_id":"github_execution_authority",
            "compatible_with_locked_decisions":True,
            "revision_requested":False,
            "action_plan":self.plan,
        }


class RepairProvider:
    name = "repair-fixture"
    def __init__(self):
        self.calls = 0
        self.validation_errors = []
    def reason(self, **kwargs):
        self.calls += 1
        self.validation_errors.append(kwargs.get("validation_error"))
        if self.calls == 1:
            return {
                "operation":"analyze",
                "decision_id":"github_execution_authority",
                "compatible_with_locked_decisions":True,
                "revision_requested":False,
                "action_plan":{
                    "executor":"github_native",
                    "payload":{"action":"close_issue"},
                },
            }
        return {
            "operation":"analyze",
            "decision_id":"github_execution_authority",
            "compatible_with_locked_decisions":True,
            "revision_requested":False,
            "action_plan":native_action_plan(),
        }


class ClosedWorldRepairProvider:
    name = "closed-world-repair-fixture"

    def __init__(self):
        self.calls = 0
        self.validation_errors = []
        self.contexts = []

    def reason(self, **kwargs):
        self.calls += 1
        self.validation_errors.append(kwargs.get("validation_error"))
        self.contexts.append(kwargs["context"])
        plan = native_action_plan()
        if self.calls == 1:
            plan["payload"]["body"] = "must-be-under-target"
        return {
            "operation":"analyze",
            "decision_id":"github_execution_authority",
            "compatible_with_locked_decisions":True,
            "revision_requested":False,
            "action_plan":plan,
        }



class NullPlanCapturingProvider:
    name = "null-plan-capturing-fixture"

    def __init__(self):
        self.calls = 0
        self.context = None

    def reason(self, **kwargs):
        self.calls += 1
        self.context = kwargs["context"]
        return {
            "operation":"analyze",
            "decision_id":None,
            "compatible_with_locked_decisions":True,
            "revision_requested":False,
            "action_plan":None,
        }



class TrackedGapProvider:
    name = "tracked-gap-fixture"

    def __init__(self):
        self.calls = 0
        self.context = None

    def reason(self, **kwargs):
        self.calls += 1
        self.context = kwargs["context"]
        repository = self.context["repository_context"]
        required = ".github/workflows/samuel-weekly-maintenance.yml"
        if required in repository.get("tracked_paths", []):
            raise AssertionError("fixture expects the required workflow to be absent")
        return {
            "operation":"analyze",
            "decision_id":"github_execution_authority",
            "compatible_with_locked_decisions":True,
            "revision_requested":False,
            "action_plan":{
                "schema_version":1,
                "research_id":"issue:24",
                "stage":"implement",
                "executor":"repository_mutation",
                "payload":{
                    "schema_version":1,
                    "repository":repository["repository"],
                    "resource":"branch",
                    "action":"create",
                    "target":{"name":"samuel/issue-24-weekly-schedule"},
                    "expected":{"absent":True},
                    "desired":{"sha":repository["observed_head_sha"]},
                },
                "expected_observation":(
                    "A fresh workload branch exists at the exact observed main head "
                    "for implementing the missing weekly maintenance schedule."
                ),
            },
        }


class NullThenFilePlanProvider:
    name = "null-then-file-plan-fixture"

    def __init__(self):
        self.calls = 0
        self.contexts = []
        self.tasks = []
        self.validation_errors = []

    def reason(self, **kwargs):
        self.calls += 1
        self.contexts.append(kwargs["context"])
        self.tasks.append(kwargs["task"])
        self.validation_errors.append(kwargs.get("validation_error"))
        if self.calls == 1:
            return {
                "operation":"analyze",
                "decision_id":None,
                "compatible_with_locked_decisions":True,
                "revision_requested":False,
                "action_plan":None,
            }
        context=kwargs["context"]
        reconciliation=context.get("completion_reconciliation")
        if not isinstance(reconciliation,dict) or reconciliation.get("required") is not True:
            raise AssertionError("second pass must be completion reconciliation")
        repository=context["repository_context"]
        branch=None
        for item in repository.get("samuel_branches",[]):
            ref=str(item.get("ref") or "")
            if (
                item.get("head_sha")==repository["observed_head_sha"]
                and ref.endswith("/samuel/issue-24-weekly")
            ):
                branch="samuel/issue-24-weekly"
                break
        if branch is None:
            raise AssertionError("fixture expects a current-head workload branch")
        return {
            "operation":"analyze",
            "decision_id":"github_execution_authority",
            "compatible_with_locked_decisions":True,
            "revision_requested":False,
            "action_plan":{
                "schema_version":1,
                "research_id":"issue:24",
                "stage":"implement",
                "executor":"repository_mutation",
                "payload":{
                    "schema_version":1,
                    "repository":repository["repository"],
                    "resource":"file",
                    "action":"create",
                    "target":{
                        "path":".github/workflows/samuel-weekly-maintenance.yml",
                        "branch":branch,
                    },
                    "expected":{"absent":True},
                    "desired":{
                        "content":"name: Samuel Weekly Maintenance\non:\n  workflow_dispatch:\n"
                    },
                    "commit_message":"Add bounded weekly maintenance workflow",
                },
                "expected_observation":(
                    "The missing weekly maintenance workflow exists on the current "
                    "workload branch."
                ),
            },
        }


class ReuseWorkloadBranchProvider:
    name = "reuse-workload-branch-fixture"

    def __init__(self):
        self.calls = 0
        self.task = None

    def reason(self, **kwargs):
        self.calls += 1
        self.task = kwargs["task"]
        branch = "samuel/issues-24-43-weekly-maintenance"
        return {
            "operation":"analyze",
            "decision_id":"github_execution_authority",
            "compatible_with_locked_decisions":True,
            "revision_requested":False,
            "action_plan":{
                "schema_version":1,
                "research_id":"issue:24",
                "stage":"implement",
                "executor":"repository_mutation",
                "payload":{
                    "schema_version":1,
                    "repository":"HyungseonSong-plasma/chatgpt-operation",
                    "resource":"file",
                    "action":"create",
                    "target":{
                        "path":".github/workflows/samuel-weekly-maintenance.yml",
                        "branch":branch,
                    },
                    "expected":{"absent":True},
                    "desired":{"content":"name: Samuel Weekly Maintenance\n"},
                    "commit_message":"Add Samuel weekly maintenance workflow",
                },
                "expected_observation":"Weekly maintenance workflow exists on the workload branch.",
            },
        }


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


def issue_payload(number=44, labels=("samuel",)):
    return {
        "number":number,
        "title":"Samuel OS",
        "body":"finish controller composition",
        "html_url":f"https://github.com/o/r/issues/{number}",
        "labels":[{"name":name} for name in labels],
    }


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



def repository_issue(number, labels=("samuel",), state="open"):
    return {
        "number":number,
        "title":f"Samuel work {number}",
        "body":f"bounded work for issue {number}",
        "state":state,
        "labels":list(labels),
    }


def native_action_plan_for(number):
    return {
        "schema_version":1,
        "research_id":f"issue:{number}",
        "stage":"implement",
        "executor":"github_native",
        "payload":{
            "action":"comment_issue",
            "repository":"HyungseonSong-plasma/chatgpt-operation",
            "target":{
                "number":number,
                "body":f"<!-- composition-root-test-{number} -->",
                "marker":f"<!-- composition-root-test-{number} -->",
            },
            "preconditions":{"issue_state":"open","comment_present":False},
            "desired_postcondition":{"comment_present":True},
        },
        "expected_observation":f"Issue #{number} contains its test marker",
    }


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
        self.assertEqual(result.to_dict()["schema_version"],4)
        self.assertIsNone(result.execution_command)


    def test_schedule_discovers_explicit_samuel_opt_in(self):
        result=controller().run_cycle(
            trigger(),
            comments=[],
            pending=[],
            repository_context={
                "open_issues":[
                    repository_issue(24),
                    repository_issue(43,labels=("observability",)),
                ]
            },
        )
        self.assertEqual(
            result.selected_work,
            {"kind":"reasoning_required","work_id":"issue:24"},
        )
        admitted=decode_admission_ledger(result.admission_write["body"])
        self.assertEqual(set(admitted),{"issue:24"})
        self.assertEqual(admitted["issue:24"]["status"],"reasoning_required")

    def test_schedule_keeps_unlabeled_open_issues_fail_closed(self):
        result=controller().run_cycle(
            trigger(),
            comments=[],
            pending=[],
            repository_context={
                "open_issues":[repository_issue(24,labels=("bug",))]
            },
        )
        self.assertEqual(result.selected_work,{"kind":"idle"})
        self.assertIsNone(result.admission_write)

    def test_owned_ready_pr_is_promoted_before_semantic_reasoning(self):
        work={
            "issue:24":{
                "work_id":"issue:24",
                "issue_number":24,
                "title":"telemetry",
                "body":"finish telemetry",
                "html_url":"https://github.com/o/r/issues/24",
                "status":"planned",
            }
        }
        state=ResearchState(
            "issue:24","finish telemetry",stage=ResearchStage.EXECUTE
        )
        state.action_queue["build"]={
            "status":"complete",
            "plan":{
                "schema_version":1,
                "research_id":"issue:24",
                "stage":"implement",
                "executor":"repository_mutation",
                "payload":{
                    "schema_version":1,
                    "repository":"HyungseonSong-plasma/chatgpt-operation",
                    "resource":"file",
                    "action":"create",
                    "target":{
                        "path":"x.py",
                        "branch":"samuel/issue-24",
                    },
                    "expected":{"absent":True},
                    "desired":{"content":"x=1\n"},
                },
                "expected_observation":"branch mutation exists",
            },
        }
        provider=Provider()
        result=controller(ReasoningProviderRegistry(provider)).run_cycle(
            trigger(),
            comments=[
                {"id":7,"body":encode_admission_ledger(work)},
                state_comment(state),
            ],
            pending=[],
            repository_context={
                "repository":"HyungseonSong-plasma/chatgpt-operation",
                "open_issues":[{
                    "number":24,
                    "title":"telemetry",
                    "body":"finish telemetry",
                    "state":"open",
                    "labels":["samuel"],
                }],
                "open_pull_requests":[{
                    "number":142,
                    "title":"ready",
                    "state":"open",
                    "draft":False,
                    "head_ref":"samuel/issue-24",
                    "head_sha":"c"*40,
                    "base_ref":"main",
                    "ci_state":"success",
                }],
            },
        )
        self.assertEqual(provider.calls,0)
        self.assertEqual(result.selected_work["kind"],"action")
        self.assertEqual(result.selected_work["plan"]["payload"]["action"],"merge_pr")
        self.assertEqual(
            result.selected_work["plan"]["payload"]["target"]["number"],142
        )
        self.assertEqual(
            result.execution_command.kind,
            ControllerCommandKind.DISPATCH_ACTION,
        )
        proposed=decode_state(result.state_write["body"])
        queued=[
            item for item in proposed.action_queue.values()
            if item.get("plan",{}).get("payload",{}).get("action")=="merge_pr"
        ]
        self.assertEqual(len(queued),1)
        self.assertEqual(queued[0]["status"],"dispatch_intent")

    def test_unowned_ready_pr_is_not_auto_promoted(self):
        work={
            "issue:24":{
                "work_id":"issue:24",
                "issue_number":24,
                "title":"telemetry",
                "body":"finish telemetry",
                "html_url":"https://github.com/o/r/issues/24",
                "status":"planned",
            }
        }
        state=ResearchState(
            "issue:24","finish telemetry",stage=ResearchStage.EXECUTE
        )
        state.action_queue["build"]={
            "status":"complete",
            "plan":{
                "schema_version":1,
                "research_id":"issue:24",
                "stage":"implement",
                "executor":"repository_mutation",
                "payload":{
                    "schema_version":1,
                    "repository":"HyungseonSong-plasma/chatgpt-operation",
                    "resource":"file",
                    "action":"create",
                    "target":{
                        "path":"x.py",
                        "branch":"samuel/issue-24",
                    },
                    "expected":{"absent":True},
                    "desired":{"content":"x=1\n"},
                },
                "expected_observation":"branch mutation exists",
            },
        }
        provider=StaticPlanProvider(native_action_plan_for(24))
        result=controller(ReasoningProviderRegistry(provider)).run_cycle(
            trigger(),
            comments=[
                {"id":7,"body":encode_admission_ledger(work)},
                state_comment(state),
            ],
            pending=[],
            repository_context={
                "repository":"HyungseonSong-plasma/chatgpt-operation",
                "open_issues":[{
                    "number":24,
                    "title":"telemetry",
                    "body":"finish telemetry",
                    "state":"open",
                    "labels":["samuel"],
                }],
                "open_pull_requests":[{
                    "number":142,
                    "title":"foreign ready",
                    "state":"open",
                    "draft":False,
                    "head_ref":"samuel/other-work",
                    "head_sha":"c"*40,
                    "base_ref":"main",
                    "ci_state":"success",
                }],
            },
        )
        self.assertEqual(provider.calls,1)
        self.assertEqual(
            result.selected_work["plan"]["payload"]["action"],
            "comment_issue",
        )

    def test_terminal_closed_workload_rolls_over_to_next_admitted_issue(self):
        work={
            "issue:44":{
                "work_id":"issue:44",
                "issue_number":44,
                "title":"Samuel OS",
                "body":"finished root workload",
                "html_url":"https://github.com/o/r/issues/44",
                "status":"planned",
            },
            "issue:24":{
                "work_id":"issue:24",
                "issue_number":24,
                "title":"Samuel work 24",
                "body":"bounded work for issue 24",
                "html_url":"",
                "status":"admitted",
            },
        }
        state=ResearchState(
            "issue:44","finished root workload",stage=ResearchStage.EXECUTE
        )
        state.action_queue["done"]={"status":"complete"}
        provider=StaticPlanProvider(native_action_plan_for(24))
        result=controller(ReasoningProviderRegistry(provider)).run_cycle(
            trigger(),
            comments=[
                {"id":7,"body":encode_admission_ledger(work)},
                state_comment(state),
            ],
            pending=[],
            repository_context={"open_issues":[repository_issue(24)]},
        )
        self.assertEqual(provider.calls,1)
        self.assertEqual(result.selected_work["kind"],"action")
        self.assertEqual(result.selected_work["work_id"],"issue:24")
        admitted=decode_admission_ledger(result.admission_write["body"])
        self.assertEqual(admitted["issue:44"]["status"],"complete")
        self.assertEqual(admitted["issue:24"]["status"],"planned")
        proposed=decode_state(result.state_write["body"])
        self.assertEqual(proposed.research_id,"issue:24")
        self.assertEqual(result.state_write["expected_previous_revision"],0)
        self.assertEqual(result.execution_command.research_id,"issue:24")

    def test_rollover_reconciles_null_plan_and_preserves_inherited_evidence(self):
        work={
            "issue:44":{
                "work_id":"issue:44",
                "issue_number":44,
                "title":"Samuel OS",
                "body":"terminal predecessor",
                "html_url":"https://github.com/o/r/issues/44",
                "status":"planned",
            },
            "issue:24":{
                "work_id":"issue:24",
                "issue_number":24,
                "title":"Weekly telemetry",
                "body":"finish weekly telemetry",
                "html_url":"https://github.com/o/r/issues/24",
                "status":"reasoning_required",
            },
        }
        state=ResearchState(
            "issue:44","terminal predecessor",stage=ResearchStage.EXECUTE,
            revision=7,
        )
        state.action_queue={
            "create-pr":{
                "status":"complete",
                "plan":{
                    "schema_version":1,
                    "research_id":"issue:44",
                    "stage":"implement",
                    "executor":"github_native",
                    "payload":{
                        "action":"create_pr",
                        "repository":"HyungseonSong-plasma/chatgpt-operation",
                        "target":{
                            "head":"samuel/issues-24-43",
                            "base":"main",
                            "title":"Telemetry maintenance",
                            "body":"Related issues: #24, #43, #44.",
                        },
                        "preconditions":{"pr_present":False},
                        "desired_postcondition":{"pr_present":True},
                    },
                    "expected_observation":"reviewable PR exists",
                },
                "completion_result":{
                    "status":"pass",
                    "observation":"PR verified",
                    "details":{
                        "after":{
                            "pr_present":True,
                            "pr_number":136,
                            "head_sha":"c"*40,
                        },
                        "provenance":{
                            "workflow_run_id":101,
                            "run_attempt":1,
                            "head_sha":"b"*40,
                            "action_id":"create-pr",
                        },
                    },
                },
            },
            "merge-pr":{
                "status":"complete",
                "plan":{
                    "schema_version":1,
                    "research_id":"issue:44",
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
                    "expected_observation":"PR #136 merged",
                },
                "completion_result":{
                    "status":"pass",
                    "observation":"merge verified",
                    "details":{
                        "after":{"merged":True,"head_sha":"c"*40},
                        "provenance":{
                            "workflow_run_id":102,
                            "run_attempt":1,
                            "head_sha":"b"*40,
                            "action_id":"merge-pr",
                        },
                    },
                },
            },
        }
        provider=NullThenFilePlanProvider()
        result=controller(ReasoningProviderRegistry(provider)).run_cycle(
            trigger(),
            comments=[
                {"id":7,"body":encode_admission_ledger(work)},
                state_comment(state),
            ],
            pending=[],
            repository_context={
                "repository":"HyungseonSong-plasma/chatgpt-operation",
                "observed_head_sha":"b"*40,
                "open_issues":[{
                    "number":24,
                    "title":"Weekly telemetry",
                    "body":"finish weekly telemetry",
                    "state":"open",
                    "labels":["samuel"],
                }],
                "open_pull_requests":[],
                "samuel_branches":[{
                    "head_sha":"b"*40,
                    "ref":"refs/heads/samuel/issue-24-weekly",
                }],
                "tracked_paths":[],
                "tracked_paths_truncated":False,
                "workflow_files":[],
            },
        )
        self.assertEqual(provider.calls,2)
        inherited=provider.contexts[0]["durable_state"]["inherited_evidence"]
        self.assertEqual(
            [item["source_action_id"] for item in inherited],
            ["create-pr","merge-pr"],
        )
        self.assertTrue(
            provider.contexts[1]["completion_reconciliation"]["required"]
        )
        self.assertEqual(result.selected_work["kind"],"action")
        self.assertEqual(result.selected_work["work_id"],"issue:24")
        self.assertEqual(
            result.selected_work["plan"]["payload"]["resource"],"file"
        )
        self.assertEqual(
            result.selected_work["plan"]["payload"]["target"]["branch"],
            "samuel/issue-24-weekly",
        )
        self.assertTrue(
            result.issue_planning["semantic_provider"]["reconciled_after_null"]
        )
        proposed=decode_state(result.state_write["body"])
        self.assertEqual(proposed.research_id,"issue:24")
        self.assertEqual(proposed.inherited_evidence,inherited)
        self.assertEqual(len(proposed.action_queue),1)

    def test_issue_trigger_admission_is_owned_by_root(self):
        issue_trigger=ControllerTrigger(
            TriggerKind.ISSUES,
            action="labeled",
            head_sha="a"*40,
            ref="refs/heads/main",
            executor_ref="main",
            executor_head_sha="b"*40,
        )
        result=controller().run_cycle(
            issue_trigger,comments=[],pending=[],issue=issue_payload()
        )
        self.assertEqual(result.selected_work,{
            "kind":"reasoning_required","work_id":"issue:44"
        })
        self.assertIsNotNone(result.admission_write)
        self.assertEqual(result.admission_write["method"],"POST")
        self.assertIsNone(result.admission_write["comment_id"])
        persisted=decode_admission_ledger(result.admission_write["body"])
        self.assertEqual(persisted["issue:44"]["status"],"reasoning_required")

    def test_issue_payload_on_non_issue_trigger_fails_closed(self):
        with self.assertRaisesRegex(
            ControllerCompositionError,"only valid for an issues trigger"
        ):
            controller().run_cycle(
                trigger(),comments=[],pending=[],issue=issue_payload()
            )

    def test_unlabeled_issue_trigger_does_not_admit_work(self):
        issue_trigger=ControllerTrigger(
            TriggerKind.ISSUES,
            action="opened",
            head_sha="a"*40,
            ref="refs/heads/main",
            executor_ref="main",
            executor_head_sha="b"*40,
        )
        result=controller().run_cycle(
            issue_trigger,comments=[],pending=[],
            issue=issue_payload(labels=("bug",)),
        )
        self.assertEqual(result.selected_work,{"kind":"idle"})
        self.assertIsNone(result.admission_write)

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

    def test_available_provider_is_invoked_and_guarded_in_root_cycle(self):
        provider=Provider()
        result=controller(ReasoningProviderRegistry(provider)).run_cycle(
            trigger(),
            comments=[admitted_comment()],
            pending=[],
            repository_context={"open_issues":[{"number":43}]},
        )
        self.assertEqual(provider.calls,1)
        self.assertEqual(result.selected_work["kind"],"action")
        self.assertIsNotNone(result.execution_command)
        self.assertTrue(result.issue_planning["semantic_provider"]["available"])
        self.assertEqual(result.issue_planning["semantic_provider"]["provider"],"fixture")
        self.assertEqual(
            result.issue_planning["semantic_provider"]["mode"],
            "AUTO_WITH_AUDIT",
        )
        self.assertEqual(result.issue_planning["outcome"],"continue")
        self.assertEqual(
            provider.context["repository_context"]["open_issues"][0]["number"],
            43,
        )


    def test_provider_repairs_malformed_nested_action_plan(self):
        provider=RepairProvider()
        result=controller(ReasoningProviderRegistry(provider)).run_cycle(
            trigger(),
            comments=[admitted_comment()],
            pending=[],
        )
        self.assertEqual(provider.calls,2)
        self.assertIsNone(provider.validation_errors[0])
        self.assertIn(
            "action plan missing fields",
            provider.validation_errors[1],
        )
        self.assertEqual(result.selected_work["kind"],"action")
        self.assertIsNotNone(result.execution_command)

    def test_provider_repairs_closed_world_native_payload(self):
        provider=ClosedWorldRepairProvider()
        result=controller(ReasoningProviderRegistry(provider)).run_cycle(
            trigger(),
            comments=[admitted_comment()],
            pending=[],
        )
        self.assertEqual(provider.calls,2)
        self.assertIsNone(provider.validation_errors[0])
        self.assertIn(
            "closed-world schema",
            provider.validation_errors[1],
        )
        payload_contract=provider.contexts[0]["execution_contracts"]["github_native"]["payload"]
        self.assertFalse(payload_contract["additional_fields"])
        self.assertEqual(
            set(payload_contract["allowed_fields"]),
            {
                "action", "repository", "target",
                "preconditions", "desired_postcondition",
            },
        )
        self.assertEqual(result.selected_work["kind"],"action")
        self.assertIsNotNone(result.execution_command)

    def test_tracked_repository_gap_can_plan_fresh_workload_branch(self):
        work={
            "issue:24":{
                "work_id":"issue:24",
                "issue_number":24,
                "title":"Weekly telemetry maintenance",
                "body":"Acceptance requires a durable scheduled workflow.",
                "html_url":"https://github.com/o/r/issues/24",
                "status":"reasoning_required",
            }
        }
        state=ResearchState(
            "issue:24",
            "Weekly telemetry maintenance",
            inherited_evidence=[{
                "schema_version":1,
                "source_research_id":"issue:44",
                "source_action_id":"merged-pr-136",
                "related_issue_number":24,
                "executor":"github_native",
                "action":"merge_pr",
                "target":{"number":136},
                "expected_observation":"PR #136 merged",
                "verified_observation":"merge verified",
                "verified_status":"pass",
                "after":{"merged":True},
            }],
        )
        provider=TrackedGapProvider()
        head="d"*40
        result=controller(ReasoningProviderRegistry(provider)).run_cycle(
            trigger(),
            comments=[
                {"id":7,"body":encode_admission_ledger(work)},
                state_comment(state),
            ],
            pending=[],
            repository_context={
                "repository":"HyungseonSong-plasma/chatgpt-operation",
                "observed_head_sha":head,
                "open_issues":[{
                    "number":24,
                    "title":"Weekly telemetry maintenance",
                    "body":"Acceptance requires a durable scheduled workflow.",
                    "state":"open",
                    "labels":["samuel"],
                }],
                "open_pull_requests":[],
                "samuel_branches":[],
                "tracked_paths":[
                    "src/chatgpt_operation/weekly_maintenance.py",
                    "tests/test_operational_telemetry.py",
                ],
                "workflow_files":[".github/workflows/ci.yml"],
            },
        )
        self.assertEqual(provider.calls,1)
        self.assertEqual(result.selected_work["kind"],"action")
        plan=result.selected_work["plan"]
        self.assertEqual(plan["executor"],"repository_mutation")
        self.assertEqual(plan["payload"]["resource"],"branch")
        self.assertEqual(
            plan["payload"]["desired"]["sha"],head
        )
        contract=provider.context["execution_contracts"]["repository_mutation"]
        self.assertFalse(contract["payload"]["additional_fields"])
        self.assertEqual(
            result.execution_command.kind,
            ControllerCommandKind.DISPATCH_ACTION,
        )
        proposed=decode_state(result.state_write["body"])
        self.assertEqual(proposed.research_id,"issue:24")
        self.assertEqual(proposed.inherited_evidence,state.inherited_evidence)

    def test_completed_workload_branch_is_reused_after_main_advances(self):
        work={
            "issue:24":{
                "work_id":"issue:24",
                "issue_number":24,
                "title":"Weekly telemetry maintenance",
                "body":"Acceptance requires a durable scheduled workflow.",
                "html_url":"https://github.com/o/r/issues/24",
                "status":"reasoning_required",
            }
        }
        old_head="a"*40
        new_head="b"*40
        branch_name="samuel/issues-24-43-weekly-maintenance"
        state=ResearchState("issue:24","Weekly telemetry maintenance")
        state.action_queue["branch-create"]={
            "status":"complete",
            "plan":{
                "schema_version":1,
                "research_id":"issue:24",
                "stage":"implement",
                "executor":"repository_mutation",
                "payload":{
                    "schema_version":1,
                    "repository":"HyungseonSong-plasma/chatgpt-operation",
                    "resource":"branch",
                    "action":"create",
                    "target":{"name":branch_name},
                    "expected":{"absent":True},
                    "desired":{"sha":old_head},
                },
                "expected_observation":"workload branch exists",
            },
        }
        provider=ReuseWorkloadBranchProvider()
        result=controller(ReasoningProviderRegistry(provider)).run_cycle(
            trigger(),
            comments=[
                {"id":7,"body":encode_admission_ledger(work)},
                state_comment(state),
            ],
            pending=[],
            repository_context={
                "repository":"HyungseonSong-plasma/chatgpt-operation",
                "observed_head_sha":new_head,
                "open_issues":[{
                    "number":24,
                    "title":"Weekly telemetry maintenance",
                    "body":"Acceptance requires a durable scheduled workflow.",
                    "state":"open",
                    "labels":["samuel"],
                }],
                "open_pull_requests":[],
                "samuel_branches":[{
                    "head_sha":old_head,
                    "ref":"refs/heads/"+branch_name,
                }],
                "tracked_paths_truncated":False,
                "tracked_paths":[
                    "src/chatgpt_operation/weekly_maintenance.py",
                ],
                "workflow_files":[".github/workflows/ci.yml"],
            },
        )
        self.assertEqual(provider.calls,1)
        self.assertIn("even if main advanced",provider.task)
        self.assertIn(
            "Do not create a replacement branch solely because",
            provider.task,
        )
        self.assertEqual(result.selected_work["kind"],"action")
        plan=result.selected_work["plan"]
        self.assertEqual(plan["payload"]["resource"],"file")
        self.assertEqual(plan["payload"]["target"]["branch"],branch_name)
        self.assertEqual(
            plan["payload"]["target"]["path"],
            ".github/workflows/samuel-weekly-maintenance.yml",
        )
        self.assertEqual(
            result.execution_command.kind,
            ControllerCommandKind.DISPATCH_ACTION,
        )

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
        self.assertEqual(
            result.execution_command.kind,
            ControllerCommandKind.DISPATCH_ACTION,
        )
        self.assertEqual(
            result.execution_command.state_revision,
            proposed.revision,
        )

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
        self.assertEqual(
            result.execution_command.kind,
            ControllerCommandKind.DISPATCH_ACTION,
        )
        self.assertEqual(result.execution_command.state_revision,proposed.revision)

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
        self.assertEqual(
            result.execution_command.kind,
            ControllerCommandKind.DISPATCH_EVIDENCE,
        )

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
        self.assertEqual(
            result.execution_command.kind,
            ControllerCommandKind.DISPATCH_DIAGNOSTIC,
        )

    def test_existing_action_intent_emits_reconcile_command(self):
        plan,state=queued_state()
        from chatgpt_operation.controller.diagnostic import record_action_dispatch_intent
        record_action_dispatch_intent(
            state,plan.idempotency_key,
            workflow="samuel-native-github.yml",ref="main",
            requested_at="2026-09-27T20:00:00Z",
            expected_head_sha="b"*40,
        )
        result=controller().run_cycle(
            trigger(),comments=[state_comment(state)],pending=[]
        )
        self.assertEqual(result.selected_work["kind"],"action_intent")
        self.assertIsNone(result.state_write)
        self.assertEqual(
            result.execution_command.kind,
            ControllerCommandKind.RECONCILE_ACTION,
        )
        self.assertEqual(result.execution_command.state_revision,state.revision)

    def test_stale_undispatched_action_intent_is_retired_for_replanning(self):
        plan,state=queued_state()
        from chatgpt_operation.controller.diagnostic import record_action_dispatch_intent
        record_action_dispatch_intent(
            state,plan.idempotency_key,
            workflow="samuel-native-github.yml",ref="main",
            requested_at="2026-09-27T20:00:00Z",
            expected_head_sha="a"*40,
        )
        result=controller().run_cycle(
            trigger(),
            comments=[admitted_comment("planned"),state_comment(state)],
            pending=[],
        )
        self.assertEqual(
            result.selected_work["kind"],"stale_action_intent"
        )
        self.assertIsNone(result.execution_command)
        self.assertIsNotNone(result.state_write)
        proposed=decode_state(result.state_write["body"])
        item=proposed.action_queue[plan.idempotency_key]
        self.assertEqual(item["status"],"rejected")
        self.assertNotIn("dispatch_intent",item)
        history=item["dispatch_intent_history"]
        self.assertEqual(
            history[-1]["retired_reason"],
            "executor_source_advanced_before_dispatch",
        )
        self.assertEqual(history[-1]["expected_head_sha"],"a"*40)
        self.assertEqual(history[-1]["observed_executor_head_sha"],"b"*40)
        admitted=decode_admission_ledger(result.admission_write["body"])
        self.assertEqual(
            admitted["issue:44"]["status"],"reasoning_required"
        )

    def test_dispatched_action_emits_observe_command(self):
        plan,state=queued_state()
        from chatgpt_operation.controller.diagnostic import (
            record_action_dispatch, record_action_dispatch_intent,
        )
        record_action_dispatch_intent(
            state,plan.idempotency_key,
            workflow="samuel-native-github.yml",ref="main",
            requested_at="2026-09-27T20:00:00Z",
            expected_head_sha="b"*40,
        )
        record_action_dispatch(state,plan.idempotency_key,{
            "workflow_path":".github/workflows/samuel-native-github.yml",
            "ref":"main",
            "correlation_id":plan.idempotency_key,
            "workflow_run_id":99,
        })
        result=controller().run_cycle(
            trigger(),comments=[state_comment(state)],pending=[]
        )
        self.assertEqual(result.selected_work["kind"],"action_observation")
        self.assertEqual(
            result.execution_command.kind,
            ControllerCommandKind.OBSERVE_ACTION,
        )
        self.assertEqual(result.execution_command.state_revision,state.revision)

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

    def test_retired_legacy_pending_work_fails_closed_in_root(self):
        work=BootstrapWork(
            "legacy",BootstrapKind.WORKFLOW,"qualification.yml",ref="main"
        )
        with self.assertRaisesRegex(
            ControllerCompositionError,"legacy static workflow work"
        ):
            controller().run_cycle(trigger(),comments=[],pending=[work])

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
