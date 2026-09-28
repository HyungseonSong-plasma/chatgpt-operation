"""Production-equivalent qualification for typed semantic planning and closed-loop execution."""
import json
import unittest
from unittest.mock import patch

from chatgpt_operation.controller.action_plan import ExecutorKind
from chatgpt_operation.controller.decisions import DecisionRegistry
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
from chatgpt_operation.controller.openai_reasoning_provider import OpenAIReasoningProvider
from chatgpt_operation.controller.reasoning_provider import ReasoningProviderRegistry
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
BRANCH="samuel/issue-24-qualification"
WORKFLOW_PATH=".github/workflows/samuel-weekly-maintenance.yml"
WORKFLOW_CONTENT=(
    "name: Samuel Weekly Maintenance\n"
    "on:\n"
    "  workflow_dispatch:\n"
    "  schedule:\n"
    "    - cron: '0 17 * * 1-5'\n"
    "jobs:\n"
    "  collect:\n"
    "    runs-on: ubuntu-latest\n"
    "    steps:\n"
    "      - run: echo \"weekday ${{ github.run_id }}\"\n"
)


class Response:
    def __init__(self,payload):
        self.payload=payload
    def __enter__(self):
        return self
    def __exit__(self,*args):
        return False
    def read(self):
        return json.dumps(self.payload).encode()


class SequencedOpenAI:
    def __init__(self):
        self.calls=0
        self.requests=[]

    def __call__(self,req,timeout):
        self.calls+=1
        body=json.loads(req.data.decode())
        self.requests.append(body)
        if self.calls==1:
            action_plan={
                "schema_version":1,
                "research_id":"issue:24",
                "stage":"implement",
                "executor":"repository_mutation",
                "payload":{
                    "schema_version":1,
                    "repository":REPOSITORY,
                    "resource":"file",
                    "action":"create",
                    "target":{"path":WORKFLOW_PATH,"branch":BRANCH},
                    "expected":{"absent":True},
                    "desired":{"content":WORKFLOW_CONTENT},
                    "commit_message":"Add qualified Samuel weekly maintenance workflow",
                },
                "expected_observation":"The scheduled maintenance workflow exists on the workload branch.",
                "decision_risk":None,
            }
        elif self.calls==2:
            action_plan={
                "schema_version":1,
                "research_id":"issue:24",
                "stage":"decide",
                "executor":"github_native",
                "payload":{
                    "action":"close_issue",
                    "repository":REPOSITORY,
                    "target":{"number":24},
                    "preconditions":{"issue_state":"open"},
                    "desired_postcondition":{"issue_state":"closed"},
                },
                "expected_observation":"Issue #24 is closed after its verified acceptance artifact exists.",
                "decision_risk":None,
            }
        else:
            raise AssertionError("qualification provider was invoked after workload completion")
        proposal={
            "operation":"analyze",
            "decision_id":"github_execution_authority",
            "compatible_with_locked_decisions":True,
            "revision_requested":False,
            "action_plan":action_plan,
        }
        return Response({"output_text":json.dumps(proposal)})


def trigger():
    return ControllerTrigger(
        TriggerKind.WORKFLOW_DISPATCH,
        action="",
        head_sha=HEAD,
        ref="refs/heads/main",
        executor_ref="main",
        executor_head_sha=HEAD,
    )


def admission_comment():
    work={
        "issue:24":{
            "work_id":"issue:24",
            "issue_number":24,
            "title":"Weekly telemetry maintenance",
            "body":(
                "Acceptance: add the bounded scheduled maintenance workflow, "
                "verify it, then close this issue."
            ),
            "html_url":"https://github.com/HyungseonSong-plasma/chatgpt-operation/issues/24",
            "status":"reasoning_required",
        }
    }
    return {"id":7,"body":encode_admission_ledger(work)}


def state_comment(state):
    return {"id":9,"body":encode_state(state)}


def repository_context(*,issue_open=True,workflow_present=False):
    paths=["src/chatgpt_operation/weekly_maintenance.py"]
    if workflow_present:
        paths.append(WORKFLOW_PATH)
    return {
        "repository":REPOSITORY,
        "observed_head_sha":HEAD,
        "open_issues":(
            [{
                "number":24,
                "title":"Weekly telemetry maintenance",
                "body":"Acceptance: add the bounded scheduled maintenance workflow, verify it, then close this issue.",
                "state":"open",
                "labels":["samuel"],
            }]
            if issue_open else []
        ),
        "open_pull_requests":[],
        "samuel_branches":[{"ref":"refs/heads/"+BRANCH,"head_sha":HEAD}],
        "tracked_paths":paths,
        "tracked_paths_truncated":False,
        "workflow_files":[WORKFLOW_PATH] if workflow_present else [],
    }


def execution_result(*,action_id,executor,run_id,observation):
    return ExecutionResult(
        research_id="issue:24",
        action_id=action_id,
        executor=executor,
        status=ExecutionStatus.PASS,
        observation=observation,
        retryable=False,
        details={
            "provenance":{
                "schema_version":1,
                "workflow_run_id":run_id,
                "run_attempt":1,
                "head_sha":HEAD,
                "action_id":action_id,
            }
        },
    )


class ProductionReasoningClosedLoopQualificationTests(unittest.TestCase):
    def test_direct_structured_plan_runs_file_to_close_to_rollover_to_idle(self):
        api=SequencedOpenAI()
        provider=OpenAIReasoningProvider(
            "secret",
            opener=api,
            allow_action_plan=True,
        )
        controller=SamuelController(
            decisions=DecisionRegistry.load("automation/samuel/decisions.json"),
            reasoning=ReasoningProviderRegistry(provider),
        )

        first=controller.run_cycle(
            trigger(),
            comments=[admission_comment()],
            pending=[],
            repository_context=repository_context(),
        )
        self.assertEqual(first.selected_work["kind"],"action")
        self.assertEqual(first.selected_work["work_id"],"issue:24")
        self.assertEqual(
            first.selected_work["plan"]["payload"]["desired"]["content"],
            WORKFLOW_CONTENT,
        )
        self.assertNotIn(
            "action_plan_json",
            api.requests[0]["text"]["format"]["schema"]["properties"],
        )
        action_id=first.selected_work["action_id"]
        state=decode_state(first.state_write["body"])
        self.assertEqual(state.action_queue[action_id]["status"],"dispatch_intent")

        receipt1={
            "workflow_path":".github/workflows/samuel-repository-mutation.yml",
            "workflow_name":"Samuel Repository Mutation",
            "ref":"main",
            "correlation_id":action_id,
            "workflow_run_id":101,
        }
        with patch(
            "chatgpt_operation.controller.execution_gateway.dispatch_workflow",
            return_value=receipt1,
        ):
            gateway1=ExecutionGateway(object()).execute(
                first.execution_command,
                state=state,
            )
        self.assertEqual(gateway1.status,GatewayStatus.RECEIPT)
        state=apply_dispatch_receipt(
            state,
            surface=gateway1.surface,
            action_id=gateway1.action_id,
            receipt=gateway1.receipt,
        )
        ledger1=decode_admission_ledger(first.admission_write["body"])

        observed1=controller.run_cycle(
            trigger(),
            comments=[
                {"id":7,"body":encode_admission_ledger(ledger1)},
                state_comment(state),
            ],
            pending=[],
            repository_context=repository_context(),
        )
        self.assertEqual(observed1.selected_work["kind"],"action_observation")
        with patch(
            "chatgpt_operation.controller.execution_gateway.observe_native_plan",
            return_value={
                "status":"MATCHED_TERMINAL",
                "matched_run_ids":[101],
                "conclusion":"success",
            },
        ):
            terminal1=ExecutionGateway(object()).execute(
                observed1.execution_command,
                state=state,
            )
        self.assertEqual(terminal1.status,GatewayStatus.TERMINAL)
        result1=execution_result(
            action_id=action_id,
            executor=ExecutorKind.REPOSITORY_MUTATION,
            run_id=101,
            observation="repository mutation verified",
        )
        ingested1=ingest_terminal_artifact(
            state,
            surface=TerminalSurface.ACTION,
            run_id=101,
            artifact_text=json.dumps(result1.to_dict(),sort_keys=True),
            gateway_result=terminal1.to_dict(),
        )
        self.assertEqual(ingested1.outcome,TerminalIngestionOutcome.APPLIED)
        state=ingested1.proposed_state
        self.assertEqual(state.action_queue[action_id]["status"],"complete")

        second=controller.run_cycle(
            trigger(),
            comments=[
                {"id":7,"body":encode_admission_ledger(ledger1)},
                state_comment(state),
            ],
            pending=[],
            repository_context=repository_context(workflow_present=True),
        )
        self.assertEqual(api.calls,2)
        self.assertEqual(second.selected_work["kind"],"action")
        self.assertEqual(
            second.selected_work["plan"]["payload"]["action"],
            "close_issue",
        )
        close_id=second.selected_work["action_id"]
        state2=decode_state(second.state_write["body"])
        ledger2=decode_admission_ledger(second.admission_write["body"])

        receipt2={
            "workflow_path":".github/workflows/samuel-native-github.yml",
            "workflow_name":"Samuel Native GitHub Executor",
            "ref":"main",
            "correlation_id":close_id,
            "workflow_run_id":202,
        }
        with patch(
            "chatgpt_operation.controller.execution_gateway.dispatch_native_plan_async",
            return_value=receipt2,
        ):
            gateway2=ExecutionGateway(object()).execute(
                second.execution_command,
                state=state2,
            )
        self.assertEqual(gateway2.status,GatewayStatus.RECEIPT)
        state2=apply_dispatch_receipt(
            state2,
            surface=gateway2.surface,
            action_id=gateway2.action_id,
            receipt=gateway2.receipt,
        )

        observed2=controller.run_cycle(
            trigger(),
            comments=[
                {"id":7,"body":encode_admission_ledger(ledger2)},
                state_comment(state2),
            ],
            pending=[],
            repository_context=repository_context(workflow_present=True),
        )
        self.assertEqual(observed2.selected_work["kind"],"action_observation")
        with patch(
            "chatgpt_operation.controller.execution_gateway.observe_native_plan",
            return_value={
                "status":"MATCHED_TERMINAL",
                "matched_run_ids":[202],
                "conclusion":"success",
            },
        ):
            terminal2=ExecutionGateway(object()).execute(
                observed2.execution_command,
                state=state2,
            )
        result2=execution_result(
            action_id=close_id,
            executor=ExecutorKind.GITHUB_NATIVE,
            run_id=202,
            observation="GitHub close_issue postcondition verified",
        )
        ingested2=ingest_terminal_artifact(
            state2,
            surface=TerminalSurface.ACTION,
            run_id=202,
            artifact_text=json.dumps(result2.to_dict(),sort_keys=True),
            gateway_result=terminal2.to_dict(),
        )
        self.assertEqual(ingested2.outcome,TerminalIngestionOutcome.APPLIED)
        final_state=ingested2.proposed_state
        self.assertEqual(final_state.action_queue[close_id]["status"],"complete")

        stopped=controller.run_cycle(
            trigger(),
            comments=[
                {"id":7,"body":encode_admission_ledger(ledger2)},
                state_comment(final_state),
            ],
            pending=[],
            repository_context=repository_context(
                issue_open=False,
                workflow_present=True,
            ),
        )
        self.assertEqual(api.calls,2)
        self.assertEqual(stopped.selected_work,{"kind":"idle"})
        self.assertIsNone(stopped.execution_command)
        self.assertIsNone(stopped.state_write)
        completed=decode_admission_ledger(stopped.admission_write["body"])
        self.assertEqual(completed["issue:24"]["status"],"complete")




class PolicyRepairingOpenAI:
    def __init__(self):
        self.calls=0
        self.requests=[]

    def __call__(self,req,timeout):
        self.calls+=1
        body=json.loads(req.data.decode())
        self.requests.append(body)
        prompt=json.loads(body["input"])
        denied=self.calls==1
        path=(
            ".github/workflows/paul-weekly-maintenance.yml"
            if denied else WORKFLOW_PATH
        )
        proposal={
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
                    "repository":REPOSITORY,
                    "resource":"file",
                    "action":"create",
                    "target":{"path":path,"branch":BRANCH},
                    "expected":{"absent":True},
                    "desired":{"content":WORKFLOW_CONTENT},
                    "commit_message":"Add weekly maintenance workflow",
                },
                "expected_observation":"weekly workflow exists",
                "decision_risk":None,
            },
        }
        if self.calls==1:
            assert prompt["validation_error"] is None
        else:
            assert "file path denied" in prompt["validation_error"]
        return Response({"output_text":json.dumps(proposal)})


class ProductionReasoningFaultQualificationTests(unittest.TestCase):
    def test_policy_denied_direct_plan_repairs_before_dispatch(self):
        api=PolicyRepairingOpenAI()
        provider=OpenAIReasoningProvider(
            "secret",
            opener=api,
            allow_action_plan=True,
        )
        controller=SamuelController(
            decisions=DecisionRegistry.load("automation/samuel/decisions.json"),
            reasoning=ReasoningProviderRegistry(provider),
        )
        cycle=controller.run_cycle(
            trigger(),
            comments=[admission_comment()],
            pending=[],
            repository_context=repository_context(),
        )
        self.assertEqual(api.calls,2)
        self.assertEqual(cycle.selected_work["kind"],"action")
        self.assertEqual(
            cycle.selected_work["plan"]["payload"]["target"]["path"],
            WORKFLOW_PATH,
        )
        self.assertNotEqual(
            cycle.selected_work["plan"]["payload"]["target"]["path"],
            ".github/workflows/paul-weekly-maintenance.yml",
        )
        state=decode_state(cycle.state_write["body"])
        action_id=cycle.selected_work["action_id"]
        self.assertEqual(state.action_queue[action_id]["status"],"dispatch_intent")
        self.assertEqual(
            cycle.issue_planning["action_plan"]["payload"]["target"]["path"],
            WORKFLOW_PATH,
        )


if __name__=="__main__":
    unittest.main()
