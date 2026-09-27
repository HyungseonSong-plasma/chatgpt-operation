import json
import unittest
from unittest.mock import patch

from chatgpt_operation.controller.action_plan import (
    ActionPlan,
    ExecutorKind,
)
from chatgpt_operation.controller.decisions import DecisionRegistry
from chatgpt_operation.controller.durable_state import (
    apply_dispatch_receipt,
    decode_state,
    encode_state,
)
from chatgpt_operation.controller.execution import (
    ExecutionResult,
    ExecutionStatus,
)
from chatgpt_operation.controller.execution_gateway import (
    ExecutionGateway,
    GatewayStatus,
)
from chatgpt_operation.controller.research import (
    ResearchStage,
    ResearchState,
)
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
from chatgpt_operation.repository.mutation import (
    PolicyError,
    load_json,
    parse_manifest,
    parse_policy,
)


HEAD="b"*40


def plan_dict():
    return {
        "schema_version":1,
        "research_id":"issue:44",
        "stage":"implement",
        "executor":"repository_mutation",
        "payload":{
            "schema_version":1,
            "repository":"HyungseonSong-plasma/chatgpt-operation",
            "resource":"branch",
            "action":"create",
            "target":{"name":"samuel/issue-43"},
            "expected":{"absent":True},
            "desired":{"sha":"a"*40},
        },
        "expected_observation":"branch exists at exact desired head",
    }


def plan():
    return ActionPlan.from_dict(plan_dict())


def state():
    p=plan()
    return ResearchState(
        "issue:44",
        "backlog closure",
        stage=ResearchStage.IMPLEMENT,
        action_queue={
            p.idempotency_key:{
                "status":"pending",
                "plan":plan_dict(),
            }
        },
        revision=3,
    )


def trigger():
    return ControllerTrigger(
        TriggerKind.WORKFLOW_DISPATCH,
        executor_ref="main",
        executor_head_sha=HEAD,
    )


class RepositoryActionSurfaceTests(unittest.TestCase):
    def test_root_routes_repository_plan_to_repository_executor(self):
        current=state()
        controller=SamuelController(
            decisions=DecisionRegistry.load("automation/samuel/decisions.json")
        )
        cycle=controller.run_cycle(
            trigger(),
            comments=[{"id":9,"body":encode_state(current)}],
            pending=[],
        )
        self.assertEqual(cycle.selected_work["kind"],"action")
        proposed=decode_state(cycle.state_write["body"])
        p=plan()
        intent=proposed.action_queue[p.idempotency_key]["dispatch_intent"]
        self.assertEqual(
            intent["workflow"],
            "samuel-repository-mutation.yml",
        )

    def test_gateway_dispatches_repository_plan_with_durable_identity(self):
        controller=SamuelController(
            decisions=DecisionRegistry.load("automation/samuel/decisions.json")
        )
        cycle=controller.run_cycle(
            trigger(),
            comments=[{"id":9,"body":encode_state(state())}],
            pending=[],
        )
        intent_state=decode_state(cycle.state_write["body"])
        p=plan()
        receipt={
            "workflow_path":".github/workflows/samuel-repository-mutation.yml",
            "ref":"main",
            "correlation_id":p.idempotency_key,
            "workflow_run_id":99,
        }
        with patch(
            "chatgpt_operation.controller.execution_gateway.dispatch_workflow",
            return_value=receipt,
        ) as dispatch:
            result=ExecutionGateway(object()).execute(
                cycle.execution_command,
                state=intent_state,
            )
        self.assertEqual(result.status,GatewayStatus.RECEIPT)
        kwargs=dispatch.call_args.kwargs
        self.assertEqual(
            kwargs["workflow"],
            "samuel-repository-mutation.yml",
        )
        self.assertEqual(
            kwargs["correlation_id"],
            p.idempotency_key,
        )
        encoded=json.loads(kwargs["inputs"]["plan_json"])
        self.assertEqual(encoded["executor"],"repository_mutation")

    def test_repository_terminal_result_completes_shared_action_lifecycle(self):
        controller=SamuelController(
            decisions=DecisionRegistry.load("automation/samuel/decisions.json")
        )
        cycle=controller.run_cycle(
            trigger(),
            comments=[{"id":9,"body":encode_state(state())}],
            pending=[],
        )
        intent_state=decode_state(cycle.state_write["body"])
        p=plan()
        receipt={
            "workflow_path":".github/workflows/samuel-repository-mutation.yml",
            "ref":"main",
            "correlation_id":p.idempotency_key,
            "workflow_run_id":99,
        }
        dispatched=apply_dispatch_receipt(
            intent_state,
            surface="action",
            action_id=p.idempotency_key,
            receipt=receipt,
        )
        result=ExecutionResult(
            research_id="issue:44",
            action_id=p.idempotency_key,
            executor=ExecutorKind.REPOSITORY_MUTATION,
            status=ExecutionStatus.PASS,
            observation="repository mutation verified by postcondition readback",
            retryable=False,
            details={
                "after":{"status":"PASS"},
                "provenance":{
                    "schema_version":1,
                    "workflow_run_id":99,
                    "run_attempt":1,
                    "head_sha":HEAD,
                    "action_id":p.idempotency_key,
                },
            },
        )
        gateway={
            "schema_version":1,
            "surface":"action",
            "action_id":p.idempotency_key,
            "status":"terminal",
            "receipt":None,
            "observation":{"status":"MATCHED_TERMINAL","conclusion":"success"},
            "terminal_run_id":99,
        }
        ingested=ingest_terminal_artifact(
            dispatched,
            surface=TerminalSurface.ACTION,
            run_id=99,
            artifact_text=json.dumps(result.to_dict()),
            gateway_result=gateway,
        )
        self.assertEqual(ingested.outcome,TerminalIngestionOutcome.APPLIED)
        self.assertEqual(
            ingested.proposed_state.action_queue[p.idempotency_key]["status"],
            "complete",
        )

    def test_samuel_policy_denies_authority_files(self):
        policy=parse_policy(
            load_json("automation/samuel/repository-mutation-policy.json")
        )
        manifest=parse_manifest({
            "schema_version":1,
            "repository":"HyungseonSong-plasma/chatgpt-operation",
            "resource":"file",
            "action":"update",
            "target":{
                "path":"automation/samuel/decisions.json",
                "branch":"samuel/issue-43",
            },
            "expected":{"sha":"a"*40},
            "desired":{"content":"{}\n"},
            "commit_message":"forbidden",
        })
        from chatgpt_operation.repository.mutation import Engine
        class NoIO:
            def get(self,*args,**kwargs):
                raise AssertionError("policy must reject before IO")
            def request(self,*args,**kwargs):
                raise AssertionError("policy must reject before IO")
        with self.assertRaises(PolicyError):
            Engine(
                NoIO(),
                repository=manifest.repository,
                policy=policy,
            ).execute(manifest)


if __name__=="__main__":
    unittest.main()
