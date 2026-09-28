"""Production-equivalent qualification for semantic planning through terminal idle."""
import json
import unittest
from unittest.mock import patch

from chatgpt_operation.controller.action_plan import ActionPlan, ExecutorKind
from chatgpt_operation.controller.decisions import DecisionRegistry
from chatgpt_operation.controller.diagnostic import enqueue_suspended_action
from chatgpt_operation.controller.durable_state import (
    apply_dispatch_receipt,
    decode_state,
    encode_state,
)
from chatgpt_operation.controller.execution import ExecutionResult, ExecutionStatus
from chatgpt_operation.controller.execution_gateway import (
    ExecutionGateway,
    GatewayStatus,
)
from chatgpt_operation.controller.issue_ingestion import (
    decode_admission_ledger,
    encode_admission_ledger,
)
from chatgpt_operation.controller.openai_reasoning_provider import (
    OpenAIReasoningProvider,
)
from chatgpt_operation.controller.reasoning_provider import ReasoningProviderRegistry
from chatgpt_operation.controller.research import ResearchStage, ResearchState
from chatgpt_operation.controller.runtime import (
    ControllerTrigger,
    SamuelController,
    TriggerKind,
)
from chatgpt_operation.controller.terminal_ingestion import (
    TerminalIngestionOutcome,
    TerminalSurface,
    ingest_terminal_artifact,
)


REPOSITORY="HyungseonSong-plasma/chatgpt-operation"
HEAD="b"*40
BRANCH="samuel/issues-24-43-weekly-maintenance-v2"
SCHEDULE_PATH="src/chatgpt_operation/weekly_schedule.py"
SCHEDULE_CONTENT=(
    "\"\"\"Code-owned cadence for the existing scheduled Samuel bootstrap.\"\"\"\n"
    "from __future__ import annotations\n"
    "from datetime import date\n"
    "\n"
    "CANONICAL_TIMEZONE=\"UTC\"\n"
    "EXISTING_BOOTSTRAP_CRON=\"55 * * * *\"\n"
    "PHASES=(\"collect\",\"analyze\",\"close\")\n"
    "\n"
    "def phase_for_day(day: date) -> str:\n"
    "    if day.weekday() <= 4:\n"
    "        return \"collect\"\n"
    "    if day.weekday() == 5:\n"
    "        return \"analyze\"\n"
    "    return \"close\"\n"
)


class Response:
    def __init__(self, payload):
        self.payload=payload
    def __enter__(self):
        return self
    def __exit__(self,*args):
        return False
    def read(self):
        return json.dumps(self.payload).encode()


class SequencedOpener:
    def __init__(self, outputs):
        self.outputs=list(outputs)
        self.requests=[]
    def __call__(self, req, timeout):
        self.requests.append(json.loads(req.data.decode()))
        if not self.outputs:
            raise AssertionError("unexpected semantic provider request")
        return Response({"output_text":json.dumps(self.outputs.pop(0))})


def trigger():
    return ControllerTrigger(
        TriggerKind.WORKFLOW_DISPATCH,
        action="",
        head_sha=HEAD,
        ref="refs/heads/main",
        executor_ref="main",
        executor_head_sha=HEAD,
    )


def repository_context(*, issue_open=True, open_pull_requests=None, schedule_present=False):
    return {
        "repository":REPOSITORY,
        "observed_head_sha":HEAD,
        "open_issues":(
            [{
                "number":24,
                "title":"Weekly telemetry maintenance",
                "body":"Acceptance requires code-owned weekly scheduling on the existing bootstrap and a reviewable PR.",
                "state":"open",
                "labels":["samuel"],
            }]
            if issue_open else []
        ),
        "open_pull_requests":list(open_pull_requests or []),
        "samuel_branches":[{
            "ref":"refs/heads/"+BRANCH,
            "head_sha":"a"*40,
        }],
        "tracked_paths_truncated":False,
        "tracked_paths":[
            "src/chatgpt_operation/weekly_maintenance.py",
            *([SCHEDULE_PATH] if schedule_present else []),
        ],
        "workflow_files":[
            ".github/workflows/ci.yml",
            ".github/workflows/samuel-bootstrap.yml",
        ],
    }


def serialized(plan):
    return {
        "schema_version":1,
        "research_id":plan.research_id,
        "stage":plan.stage.value,
        "executor":plan.executor.value,
        "payload":dict(plan.payload),
        "expected_observation":plan.expected_observation,
        "decision_risk":None,
    }


def initial_state_and_ledger():
    state=ResearchState(
        "issue:24",
        "Weekly telemetry maintenance",
        stage=ResearchStage.IMPLEMENT,
        revision=10,
    )
    denied=ActionPlan.from_dict({
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
                "path":".github/workflows/paul-weekly-maintenance.yml",
                "branch":BRANCH,
            },
            "expected":{"absent":True},
            "desired":{"content":"name: denied\n"},
            "commit_message":"Attempt denied workflow",
        },
        "expected_observation":"denied workflow would exist",
    })
    enqueue_suspended_action(state,denied)
    denied_id=denied.idempotency_key
    state.action_queue[denied_id]["status"]="suspended"
    state.execution_results[denied_id]={
        "schema_version":1,
        "research_id":"issue:24",
        "action_id":denied_id,
        "executor":"repository_mutation",
        "status":"failed",
        "observation":"repository mutation failed closed",
        "retryable":False,
        "details":{
            "provider":"repository-native",
            "error_type":"PolicyError",
            "error":"file path denied: .github/workflows/paul-weekly-maintenance.yml",
            "governance_retryable":False,
        },
    }
    ledger={
        "issue:24":{
            "work_id":"issue:24",
            "issue_number":24,
            "title":"Weekly telemetry maintenance",
            "body":"Acceptance requires code-owned weekly scheduling on the existing bootstrap and a reviewable PR.",
            "html_url":"https://github.com/HyungseonSong-plasma/chatgpt-operation/issues/24",
            "status":"planned",
        }
    }
    return state,ledger,denied_id


def comments(ledger,state):
    return [
        {"id":7,"body":encode_admission_ledger(ledger)},
        {"id":9,"body":encode_state(state)},
    ]


def file_plan():
    return {
        "schema_version":1,
        "research_id":"issue:24",
        "stage":"implement",
        "executor":"repository_mutation",
        "payload":{
            "schema_version":1,
            "repository":REPOSITORY,
            "resource":"file",
            "action":"create",
            "target":{"path":SCHEDULE_PATH,"branch":BRANCH},
            "expected":{"absent":True},
            "desired":{"content":SCHEDULE_CONTENT},
            "commit_message":"Add code-owned Paul weekly maintenance schedule",
        },
        "expected_observation":"Code-owned weekly schedule integration exists on the workload branch.",
        "decision_risk":None,
    }


def create_pr_plan():
    return {
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
                "title":"Add scheduled weekly maintenance",
                "body":"Implements issue #24 weekly-maintenance scheduling.",
            },
            "preconditions":{"pr_present":False},
            "desired_postcondition":{"pr_present":True},
        },
        "expected_observation":"A reviewable pull request exists for the workload branch.",
        "decision_risk":None,
    }


def close_issue_plan():
    return {
        "schema_version":1,
        "research_id":"issue:24",
        "stage":"execute",
        "executor":"github_native",
        "payload":{
            "action":"close_issue",
            "repository":REPOSITORY,
            "target":{"number":24},
            "preconditions":{"issue_state":"open"},
            "desired_postcondition":{"issue_state":"closed"},
        },
        "expected_observation":"Issue #24 is closed after verified implementation.",
        "decision_risk":None,
    }


def proposal(action_plan):
    return {
        "operation":"analyze",
        "decision_id":"github_execution_authority",
        "compatible_with_locked_decisions":True,
        "revision_requested":False,
        "action_plan":action_plan,
    }


class ProviderClosedLoopQualificationTests(unittest.TestCase):
    def _finish_action(
        self,
        *,
        controller,
        cycle,
        ledger,
        context,
        run_id,
    ):
        self.assertEqual(cycle.selected_work["kind"],"action")
        self.assertIsNotNone(cycle.state_write)
        self.assertIsNotNone(cycle.execution_command)
        action_id=cycle.selected_work["action_id"]
        plan=ActionPlan.from_dict(cycle.selected_work["plan"])
        intent_state=decode_state(cycle.state_write["body"])
        if cycle.admission_write is not None:
            ledger=decode_admission_ledger(cycle.admission_write["body"])

        workflow=(
            "samuel-repository-mutation.yml"
            if plan.executor is ExecutorKind.REPOSITORY_MUTATION
            else "samuel-native-github.yml"
        )
        receipt={
            "workflow_path":".github/workflows/"+workflow,
            "ref":"main",
            "correlation_id":action_id,
            "workflow_run_id":run_id,
        }
        gateway=ExecutionGateway(object())
        if plan.executor is ExecutorKind.REPOSITORY_MUTATION:
            dispatch_patch=patch(
                "chatgpt_operation.controller.execution_gateway.dispatch_workflow",
                return_value=receipt,
            )
        else:
            dispatch_patch=patch(
                "chatgpt_operation.controller.execution_gateway.dispatch_native_plan_async",
                return_value=receipt,
            )
        with dispatch_patch:
            dispatched=gateway.execute(
                cycle.execution_command,
                state=intent_state,
            )
        self.assertEqual(dispatched.status,GatewayStatus.RECEIPT)
        dispatched_state=apply_dispatch_receipt(
            intent_state,
            surface="action",
            action_id=action_id,
            receipt=receipt,
        )

        observation_cycle=controller.run_cycle(
            trigger(),
            comments=comments(ledger,dispatched_state),
            pending=[],
            repository_context=context,
        )
        self.assertEqual(
            observation_cycle.selected_work["kind"],
            "action_observation",
        )
        self.assertIsNotNone(observation_cycle.execution_command)
        with patch(
            "chatgpt_operation.controller.execution_gateway.observe_native_plan",
            return_value={
                "status":"MATCHED_TERMINAL",
                "matched_run_ids":[run_id],
                "conclusion":"success",
            },
        ):
            terminal=gateway.execute(
                observation_cycle.execution_command,
                state=dispatched_state,
            )
        self.assertEqual(terminal.status,GatewayStatus.TERMINAL)
        result=ExecutionResult(
            research_id="issue:24",
            action_id=action_id,
            executor=plan.executor,
            status=ExecutionStatus.PASS,
            observation="executor postcondition verified",
            retryable=False,
            details={
                "after":{"verified":True},
                "provenance":{
                    "schema_version":1,
                    "workflow_run_id":run_id,
                    "run_attempt":1,
                    "head_sha":HEAD,
                    "action_id":action_id,
                },
            },
        )
        ingested=ingest_terminal_artifact(
            dispatched_state,
            surface=TerminalSurface.ACTION,
            run_id=run_id,
            artifact_text=json.dumps(result.to_dict(),sort_keys=True),
            gateway_result=terminal.to_dict(),
        )
        self.assertEqual(ingested.outcome,TerminalIngestionOutcome.APPLIED)
        self.assertIsNotNone(ingested.proposed_state)
        final_state=ingested.proposed_state
        self.assertEqual(final_state.action_queue[action_id]["status"],"complete")
        return final_state,ledger,plan

    def test_provider_to_terminal_rollover_and_idle_with_multiline_schedule_source(self):
        opener=SequencedOpener([
            {
                "operation":"propose_revision",
                "decision_id":"workflow_file_mutation_governance",
                "compatible_with_locked_decisions":True,
                "revision_requested":True,
                "action_plan":None,
            },
            proposal(file_plan()),
            proposal(create_pr_plan()),
            proposal(close_issue_plan()),
        ])
        provider=OpenAIReasoningProvider(
            "test",
            opener=opener,
            allow_action_plan=True,
        )
        controller=SamuelController(
            decisions=DecisionRegistry.load("automation/samuel/decisions.json"),
            reasoning=ReasoningProviderRegistry(provider),
        )
        state,ledger,denied_id=initial_state_and_ledger()

        # Suspended policy failure stays on issue:24 and enters bounded semantic
        # repair. Reproducing the live invented governance revision must repair to
        # executable source work on the already scheduled bootstrap surface.
        first=controller.run_cycle(
            trigger(),
            comments=comments(ledger,state),
            pending=[],
            repository_context=repository_context(),
        )
        self.assertEqual(len(opener.requests),2)
        second_prompt=json.loads(opener.requests[1]["input"])
        self.assertIn(
            "decision_id must be null or reference an existing locked decision",
            second_prompt["validation_error"],
        )
        scheduler=second_prompt["reasoning_context"]["repository_context"][
            "scheduler_surfaces"
        ]
        self.assertEqual(
            scheduler,
            [{
                "workflow":".github/workflows/samuel-bootstrap.yml",
                "event":"schedule",
                "cron":"55 * * * *",
                "mutation_required":False,
            }],
        )
        schema=opener.requests[1]["text"]["format"]["schema"]
        self.assertIn("action_plan",schema["properties"])
        self.assertNotIn("action_plan_json",schema["properties"])
        state,ledger,created=self._finish_action(
            controller=controller,
            cycle=first,
            ledger=ledger,
            context=repository_context(),
            run_id=501,
        )
        self.assertEqual(created.executor,ExecutorKind.REPOSITORY_MUTATION)
        self.assertEqual(
            created.payload["desired"]["content"],
            SCHEDULE_CONTENT,
        )
        self.assertEqual(state.action_queue[denied_id]["status"],"suspended")

        # The same workload continues from an allowed src/** mutation and produces a reviewable PR.
        pr_cycle=controller.run_cycle(
            trigger(),
            comments=comments(ledger,state),
            pending=[],
            repository_context=repository_context(schedule_present=True),
        )
        self.assertEqual(len(opener.requests),3)
        state,ledger,pr_plan=self._finish_action(
            controller=controller,
            cycle=pr_cycle,
            ledger=ledger,
            context=repository_context(schedule_present=True),
            run_id=502,
        )
        self.assertEqual(pr_plan.payload["action"],"create_pr")

        # A green workload-owned PR is merged by deterministic controller logic,
        # without consuming another semantic-provider response.
        ready_pr={
            "number":200,
            "state":"open",
            "draft":False,
            "ci_state":"success",
            "head_ref":BRANCH,
            "head_sha":"c"*40,
        }
        merge_cycle=controller.run_cycle(
            trigger(),
            comments=comments(ledger,state),
            pending=[],
            repository_context=repository_context(
                schedule_present=True,
                open_pull_requests=[ready_pr],
            ),
        )
        self.assertEqual(len(opener.requests),3)
        self.assertEqual(
            merge_cycle.selected_work["reasoning_outcome"],
            "deterministic_ready_pr",
        )
        state,ledger,merge_plan=self._finish_action(
            controller=controller,
            cycle=merge_cycle,
            ledger=ledger,
            context=repository_context(
                schedule_present=True,
                open_pull_requests=[ready_pr],
            ),
            run_id=503,
        )
        self.assertEqual(merge_plan.payload["action"],"merge_pr")

        # After merge evidence, semantic reasoning closes the active issue.
        close_cycle=controller.run_cycle(
            trigger(),
            comments=comments(ledger,state),
            pending=[],
            repository_context=repository_context(schedule_present=True),
        )
        self.assertEqual(len(opener.requests),4)
        state,ledger,close_plan=self._finish_action(
            controller=controller,
            cycle=close_cycle,
            ledger=ledger,
            context=repository_context(schedule_present=True),
            run_id=504,
        )
        self.assertEqual(close_plan.payload["action"],"close_issue")

        # Once the repository observation shows the issue closed, the old
        # governed nonretryable failure remains auditable but cannot block
        # rollover. The queue is exhausted and Samuel stops as idle.
        stopped=controller.run_cycle(
            trigger(),
            comments=comments(ledger,state),
            pending=[],
            repository_context=repository_context(
                issue_open=False,
                schedule_present=True,
            ),
        )
        self.assertEqual(stopped.selected_work,{"kind":"idle"})
        self.assertIsNone(stopped.execution_command)
        self.assertIsNone(stopped.state_write)
        self.assertIsNotNone(stopped.admission_write)
        final_ledger=decode_admission_ledger(stopped.admission_write["body"])
        self.assertEqual(final_ledger["issue:24"]["status"],"complete")
        self.assertEqual(len(opener.requests),4)
        self.assertEqual(opener.outputs,[])


if __name__=="__main__":
    unittest.main()
