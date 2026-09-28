import tempfile
import unittest
from pathlib import Path

from chatgpt_operation.controller.action_plan import ActionPlan
from chatgpt_operation.controller.diagnostic import enqueue_suspended_action
from chatgpt_operation.controller.merge_recovery import (
    conflict_main_file_snapshots,
    conflict_recovery_branch_name,
    conflict_recovery_branch_plan,
    conflicted_workload_pull_requests,
    rejected_merge_targets,
)
from chatgpt_operation.controller.preflight import preflight_semantic_plan
from chatgpt_operation.controller.research import ResearchStage, ResearchState
from chatgpt_operation.controller.runtime import _owned_ready_pr_plan


REPOSITORY="HyungseonSong-plasma/chatgpt-operation"
OLD_BRANCH="samuel/issues-24-43-weekly-maintenance-v2"
OLD_HEAD="f"*40
MAIN_HEAD="a"*40


def create_pr_plan():
    return ActionPlan.from_dict({
        "schema_version":1,
        "research_id":"issue:24",
        "stage":"execute",
        "executor":"github_native",
        "payload":{
            "action":"create_pr",
            "repository":REPOSITORY,
            "target":{
                "head":OLD_BRANCH,
                "base":"main",
                "title":"weekly",
                "body":"weekly",
            },
            "preconditions":{"pr_present":False},
            "desired_postcondition":{"pr_present":True},
        },
        "expected_observation":"PR exists",
    })


def merge_plan():
    return ActionPlan.from_dict({
        "schema_version":1,
        "research_id":"issue:24",
        "stage":"execute",
        "executor":"github_native",
        "payload":{
            "action":"merge_pr",
            "repository":REPOSITORY,
            "target":{"number":173,"expected_head_sha":OLD_HEAD},
            "desired_postcondition":{"merged":True},
        },
        "expected_observation":"PR merged",
    })


def state_with_rejected_merge():
    state=ResearchState("issue:24","weekly",stage=ResearchStage.EXECUTE)
    for plan,status in ((create_pr_plan(),"complete"),(merge_plan(),"rejected")):
        enqueue_suspended_action(state,plan)
        action_id=plan.idempotency_key
        state.action_queue[action_id]["status"]=status
        state.action_queue[action_id]["completion_result"]={
            "schema_version":1,
            "research_id":"issue:24",
            "action_id":action_id,
            "executor":plan.executor.value,
            "status":"pass" if status=="complete" else "rejected",
            "observation":"verified" if status=="complete" else "mergeable=false",
            "retryable":False,
            "details":(
                {}
                if status=="complete"
                else {
                    "before":{
                        "merged":False,
                        "head_sha":OLD_HEAD,
                        "mergeable":False,
                        "ci":"success",
                    },
                    "required":{
                        "head_sha":OLD_HEAD,
                        "mergeable":True,
                        "ci":"success",
                    },
                }
            ),
        }
    return state


def context(*, include_recovery=False):
    recovery="samuel/issue-24-refresh-"+MAIN_HEAD[:12]
    branches=[
        {"ref":"refs/heads/"+OLD_BRANCH,"head_sha":OLD_HEAD},
    ]
    if include_recovery:
        branches.append({"ref":"refs/heads/"+recovery,"head_sha":MAIN_HEAD})
    return {
        "repository":REPOSITORY,
        "observed_head_sha":MAIN_HEAD,
        "open_pull_requests":[{
            "number":173,
            "state":"open",
            "draft":False,
            "ci_state":"success",
            "head_ref":OLD_BRANCH,
            "head_sha":OLD_HEAD,
            "base_ref":"main",
        }],
        "samuel_branches":branches,
    }


class MergeRecoveryTests(unittest.TestCase):
    def test_rejected_exact_merge_is_never_repromoted(self):
        state=state_with_rejected_merge()
        self.assertEqual(rejected_merge_targets(state),{(173,OLD_HEAD)})
        self.assertIsNone(_owned_ready_pr_plan(state,context()))

    def test_rejected_merge_projects_conflict_and_fresh_branch(self):
        state=state_with_rejected_merge()
        conflicts=conflicted_workload_pull_requests(state,context())
        self.assertEqual(conflicts[0]["number"],173)
        self.assertEqual(conflicts[0]["head_ref"],OLD_BRANCH)
        name=conflict_recovery_branch_name(state,context())
        self.assertEqual(name,"samuel/issue-24-refresh-"+MAIN_HEAD[:12])
        plan=conflict_recovery_branch_plan(state,context())
        self.assertIsNotNone(plan)
        self.assertEqual(plan.payload["resource"],"branch")
        self.assertEqual(plan.payload["target"]["name"],name)
        self.assertEqual(plan.payload["desired"]["sha"],MAIN_HEAD)
        self.assertIsNone(
            conflict_recovery_branch_plan(state,context(include_recovery=True))
        )

    def test_current_main_overlap_snapshot_is_exact_and_bounded(self):
        state=state_with_rejected_merge()
        file_plan=ActionPlan.from_dict({
            "schema_version":1,
            "research_id":"issue:24",
            "stage":"implement",
            "executor":"repository_mutation",
            "payload":{
                "schema_version":1,
                "repository":REPOSITORY,
                "resource":"file",
                "action":"create",
                "target":{"path":"src/x.py","branch":OLD_BRANCH},
                "expected":{"absent":True},
                "desired":{"content":"OLD=True\n"},
                "commit_message":"old",
            },
            "expected_observation":"old file exists",
        })
        enqueue_suspended_action(state,file_plan)
        state.action_queue[file_plan.idempotency_key]["status"]="complete"
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"src/x.py"
            path.parent.mkdir(parents=True)
            path.write_text("MAIN=True\n",encoding="utf-8")
            snapshots=conflict_main_file_snapshots(
                state,context(),root=tmp
            )
        self.assertEqual(len(snapshots),1)
        self.assertEqual(snapshots[0]["path"],"src/x.py")
        self.assertEqual(snapshots[0]["content"],"MAIN=True\n")
        self.assertEqual(len(snapshots[0]["git_blob_sha"]),40)

    def test_preflight_forbids_more_work_on_conflicted_branch(self):
        state=state_with_rejected_merge()
        repository_context=context(include_recovery=True)
        repository_context["conflicted_workload_branches"]=[OLD_BRANCH]
        plan=ActionPlan.from_dict({
            "schema_version":1,
            "research_id":"issue:24",
            "stage":"implement",
            "executor":"repository_mutation",
            "payload":{
                "schema_version":1,
                "repository":REPOSITORY,
                "resource":"file",
                "action":"create",
                "target":{"path":"docs/more.md","branch":OLD_BRANCH},
                "expected":{"absent":True},
                "desired":{"content":"no\n"},
                "commit_message":"no",
            },
            "expected_observation":"must not execute",
        })
        failure=preflight_semantic_plan(
            plan=plan,
            progress=None,
            completion_claim=None,
            issue_body="no acceptance section",
            state=state,
            repository_context=repository_context,
        )
        self.assertEqual(failure.code,"conflicted_workload_branch")


if __name__=="__main__":
    unittest.main()
