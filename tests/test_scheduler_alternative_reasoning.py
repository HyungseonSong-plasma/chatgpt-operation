import unittest
from datetime import datetime, timezone

from chatgpt_operation.controller.decisions import DecisionRegistry
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
from chatgpt_operation.weekly_schedule import SCHEDULER_CAPABILITY


REPOSITORY="HyungseonSong-plasma/chatgpt-operation"
HEAD="b"*40
BRANCH="samuel/issues-24-43-weekly-maintenance-v2"


class AlternativeRepairProvider:
    name="alternative-repair-fixture"

    def __init__(self):
        self.calls=0
        self.validation_errors=[]
        self.contexts=[]
        self.tasks=[]

    def reason(self,**kwargs):
        self.calls+=1
        self.validation_errors.append(kwargs.get("validation_error"))
        self.contexts.append(kwargs["context"])
        self.tasks.append(kwargs["task"])
        if self.calls==1:
            return {
                "operation":"propose_revision",
                "decision_id":"github_execution_authority",
                "compatible_with_locked_decisions":False,
                "revision_requested":True,
                "action_plan":None,
                "blocker":{
                    "capability":"workflow_file_mutation",
                    "alternatives_considered":[],
                    "exhausted":True,
                },
            }
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
                    "repository":REPOSITORY,
                    "resource":"file",
                    "action":"create",
                    "target":{
                        "path":"src/chatgpt_operation/weekly_schedule_extension.py",
                        "branch":BRANCH,
                    },
                    "expected":{"absent":True},
                    "desired":{
                        "content":"# code-owned weekly cadence extension\n"
                    },
                    "commit_message":"Implement weekly cadence on existing scheduler",
                },
                "expected_observation":(
                    "Code-owned weekly cadence implementation exists on the workload branch."
                ),
            },
            "blocker":None,
        }


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
    return {
        "id":7,
        "body":encode_admission_ledger({
            "issue:24":{
                "work_id":"issue:24",
                "issue_number":24,
                "title":"Weekly telemetry maintenance",
                "body":(
                    "Use a durable scheduler for Mon-Fri collection, Saturday analysis, "
                    "and Sunday bounded improvement."
                ),
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
            "title":"Weekly telemetry maintenance",
            "body":(
                "Use a durable scheduler for Mon-Fri collection, Saturday analysis, "
                "and Sunday bounded improvement."
            ),
            "state":"open",
            "labels":["samuel"],
        }],
        "open_pull_requests":[],
        "samuel_branches":[{
            "ref":"refs/heads/"+BRANCH,
            "head_sha":"a"*40,
        }],
        "tracked_paths":[
            ".github/workflows/samuel-bootstrap.yml",
            "src/chatgpt_operation/weekly_maintenance.py",
        ],
        "tracked_paths_truncated":False,
        "workflow_files":[".github/workflows/samuel-bootstrap.yml"],
    }


class SchedulerAlternativeReasoningTests(unittest.TestCase):
    def test_known_scheduler_forces_bounded_repair_before_revision(self):
        provider=AlternativeRepairProvider()
        controller=SamuelController(
            decisions=DecisionRegistry.load("automation/samuel/decisions.json"),
            reasoning=ReasoningProviderRegistry(provider),
            now=lambda:datetime(2026,9,28,6,55,tzinfo=timezone.utc),
        )
        cycle=controller.run_cycle(
            trigger(),
            comments=[admission_comment()],
            pending=[],
            repository_context=repository_context(),
        )
        self.assertEqual(provider.calls,2)
        self.assertIsNone(provider.validation_errors[0])
        self.assertIn(
            "known alternative existing_scheduled_runtime",
            provider.validation_errors[1],
        )
        contract=provider.contexts[0]["execution_contracts"]["scheduled_runtime"]
        self.assertTrue(contract["existing_durable_scheduler"])
        self.assertFalse(contract["workflow_file_mutation_required"])
        self.assertEqual(contract["capability"],SCHEDULER_CAPABILITY)
        self.assertEqual(contract["current_slot"]["phase"],"collect")
        self.assertIn("Before proposing revision",provider.tasks[0])
        self.assertEqual(cycle.selected_work["kind"],"action")
        self.assertEqual(cycle.selected_work["work_id"],"issue:24")
        self.assertEqual(
            cycle.selected_work["plan"]["payload"]["target"]["path"],
            "src/chatgpt_operation/weekly_schedule_extension.py",
        )
        self.assertIsNotNone(cycle.execution_command)
        ledger=decode_admission_ledger(cycle.admission_write["body"])
        self.assertEqual(ledger["issue:24"]["status"],"planned")


if __name__=="__main__":
    unittest.main()
