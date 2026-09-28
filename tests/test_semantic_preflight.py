import unittest

from chatgpt_operation.controller.action_plan import ActionPlan
from chatgpt_operation.controller.diagnostic import enqueue_suspended_action
from chatgpt_operation.controller.preflight import (
    eligible_acceptance_criteria,
    extract_acceptance_criteria,
    integrated_acceptance_evidence,
    preflight_semantic_plan,
    verified_evidence_ids,
)
from chatgpt_operation.controller.research import ResearchStage, ResearchState


REPOSITORY="HyungseonSong-plasma/chatgpt-operation"
HEAD="a"*40
BRANCH="samuel/issue-24-preflight"
BODY="""## Purpose

Weekly maintenance.

## Acceptance

- scheduler is durable
- retry handling is deterministic
- closure is backed by evidence
"""


def context():
    return {
        "repository":REPOSITORY,
        "observed_head_sha":HEAD,
        "samuel_branches":[
            {"ref":"refs/heads/"+BRANCH,"head_sha":"b"*40},
        ],
        "open_pull_requests":[],
    }


def branch_plan(sha=HEAD):
    return ActionPlan.from_dict({
        "schema_version":1,
        "research_id":"issue:24",
        "stage":"implement",
        "executor":"repository_mutation",
        "payload":{
            "schema_version":1,
            "repository":REPOSITORY,
            "resource":"branch",
            "action":"create",
            "target":{"name":"samuel/new-work"},
            "expected":{"absent":True},
            "desired":{"sha":sha},
        },
        "expected_observation":"workload branch exists",
    })


def file_plan(branch=BRANCH, path="src/chatgpt_operation/x.py"):
    return ActionPlan.from_dict({
        "schema_version":1,
        "research_id":"issue:24",
        "stage":"implement",
        "executor":"repository_mutation",
        "payload":{
            "schema_version":1,
            "repository":REPOSITORY,
            "resource":"file",
            "action":"create",
            "target":{"path":path,"branch":branch},
            "expected":{"absent":True},
            "desired":{"content":"X=1\n"},
            "commit_message":"Add x",
        },
        "expected_observation":"code exists",
    })


def close_plan():
    return ActionPlan.from_dict({
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
        "expected_observation":"issue closed",
    })


def state():
    return ResearchState(
        "issue:24",
        "weekly maintenance",
        stage=ResearchStage.IMPLEMENT,
    )


def create_pr_plan(branch=BRANCH):
    return ActionPlan.from_dict({
        "schema_version":1,
        "research_id":"issue:24",
        "stage":"execute",
        "executor":"github_native",
        "payload":{
            "action":"create_pr",
            "repository":REPOSITORY,
            "target":{
                "head":branch,
                "base":"main",
                "title":"bounded work",
                "body":"reviewable work",
            },
            "preconditions":{"pr_present":False},
            "desired_postcondition":{"pr_present":True},
        },
        "expected_observation":"reviewable PR exists",
    })


def merge_pr_plan(number=99, head_sha="c"*40):
    return ActionPlan.from_dict({
        "schema_version":1,
        "research_id":"issue:24",
        "stage":"execute",
        "executor":"github_native",
        "payload":{
            "action":"merge_pr",
            "repository":REPOSITORY,
            "target":{"number":number,"expected_head_sha":head_sha},
            "desired_postcondition":{"merged":True},
        },
        "expected_observation":"reviewed PR is merged",
    })


def mark_complete(current, plan, *, progress=None, details=None):
    enqueue_suspended_action(current,plan)
    action_id=plan.idempotency_key
    current.action_queue[action_id]["status"]="complete"
    current.action_queue[action_id]["completion_result"]={
        "schema_version":1,
        "research_id":"issue:24",
        "action_id":action_id,
        "executor":plan.executor.value,
        "status":"pass",
        "observation":"verified",
        "retryable":False,
        "details":{} if details is None else details,
    }
    if progress is not None:
        current.action_queue[action_id]["progress"]=progress
    return action_id


class SemanticPreflightTests(unittest.TestCase):
    def test_extracts_only_acceptance_bullets(self):
        self.assertEqual(
            extract_acceptance_criteria(BODY),
            (
                "scheduler is durable",
                "retry handling is deterministic",
                "closure is backed by evidence",
            ),
        )

    def test_rejects_duplicate_action_before_dispatch(self):
        current=state()
        plan=file_plan()
        enqueue_suspended_action(current,plan)
        failure=preflight_semantic_plan(
            plan=plan,
            progress={
                "criterion":"scheduler is durable",
                "rationale":"adds implementation",
            },
            completion_claim=None,
            issue_body=BODY,
            state=current,
            repository_context=context(),
        )
        self.assertEqual(failure.code,"duplicate_action")
        self.assertIn("PREFLIGHT_REJECTED",failure.as_validation_error())

    def test_rejects_stale_branch_base(self):
        failure=preflight_semantic_plan(
            plan=branch_plan("c"*40),
            progress={
                "criterion":"scheduler is durable",
                "rationale":"creates implementation branch",
            },
            completion_claim=None,
            issue_body=BODY,
            state=state(),
            repository_context=context(),
        )
        self.assertEqual(failure.code,"stale_branch_base")

    def test_rejects_missing_file_target_branch(self):
        failure=preflight_semantic_plan(
            plan=file_plan("samuel/missing"),
            progress={
                "criterion":"scheduler is durable",
                "rationale":"adds scheduler code",
            },
            completion_claim=None,
            issue_body=BODY,
            state=state(),
            repository_context=context(),
        )
        self.assertEqual(failure.code,"missing_target_branch")

    def test_rejects_non_close_without_exact_acceptance_progress(self):
        failure=preflight_semantic_plan(
            plan=file_plan(),
            progress=None,
            completion_claim=None,
            issue_body=BODY,
            state=state(),
            repository_context=context(),
        )
        self.assertEqual(failure.code,"missing_acceptance_progress")
        failure=preflight_semantic_plan(
            plan=file_plan(),
            progress={
                "criterion":"invented criterion",
                "rationale":"not accepted",
            },
            completion_claim=None,
            issue_body=BODY,
            state=state(),
            repository_context=context(),
        )
        self.assertEqual(failure.code,"unknown_acceptance_criterion")

    def test_terminal_completion_result_is_verified_evidence(self):
        current=state()
        evidence=file_plan(path="src/chatgpt_operation/evidence.py")
        action_id=mark_complete(current,evidence)
        self.assertIn(action_id,verified_evidence_ids(current))

    def test_progress_can_continue_until_branch_is_merged(self):
        current=state()
        evidence=file_plan(path="src/chatgpt_operation/evidence.py")
        mark_complete(
            current,
            evidence,
            progress={
                "criterion":"scheduler is durable",
                "rationale":"implementation landed on review branch",
            },
        )
        failure=preflight_semantic_plan(
            plan=file_plan(path="src/chatgpt_operation/evidence_test.py"),
            progress={
                "criterion":"scheduler is durable",
                "rationale":"adds verification before merge",
            },
            completion_claim=None,
            issue_body=BODY,
            state=current,
            repository_context=context(),
        )
        self.assertIsNone(failure)
        self.assertEqual(integrated_acceptance_evidence(current),{})

    def test_rejects_progress_for_criterion_already_integrated_by_merged_pr(self):
        current=state()
        evidence=file_plan(path="src/chatgpt_operation/evidence.py")
        evidence_id=mark_complete(
            current,
            evidence,
            progress={
                "criterion":"scheduler is durable",
                "rationale":"implementation on bounded branch",
            },
        )
        create_pr=create_pr_plan()
        mark_complete(
            current,
            create_pr,
            details={"after":{"pr_number":99,"head_sha":"c"*40}},
        )
        merge_pr=merge_pr_plan()
        mark_complete(
            current,
            merge_pr,
            details={"after":{"merged":True,"head_sha":"c"*40}},
        )

        integrated=integrated_acceptance_evidence(current)
        self.assertEqual(integrated["scheduler is durable"],(evidence_id,))

        failure=preflight_semantic_plan(
            plan=file_plan(path="src/chatgpt_operation/reprove.py"),
            progress={
                "criterion":"scheduler is durable",
                "rationale":"must not re-prove merged progress",
            },
            completion_claim=None,
            issue_body=BODY,
            state=current,
            repository_context=context(),
        )
        self.assertEqual(failure.code,"acceptance_already_integrated")
        self.assertEqual(
            failure.evidence["evidence_action_ids"],
            [evidence_id],
        )

    def test_eligible_acceptance_excludes_integrated_criteria(self):
        current=state()
        evidence=file_plan(path="src/chatgpt_operation/evidence.py")
        evidence_id=mark_complete(
            current,
            evidence,
            progress={
                "criterion":"scheduler is durable",
                "rationale":"implementation on bounded branch",
            },
        )
        create_pr=create_pr_plan()
        mark_complete(
            current,
            create_pr,
            details={"after":{"pr_number":99,"head_sha":"c"*40}},
        )
        merge_pr=merge_pr_plan()
        mark_complete(
            current,
            merge_pr,
            details={"after":{"merged":True,"head_sha":"c"*40}},
        )
        self.assertEqual(
            integrated_acceptance_evidence(current)["scheduler is durable"],
            (evidence_id,),
        )
        self.assertEqual(
            eligible_acceptance_criteria(BODY,current),
            (
                "retry handling is deterministic",
                "closure is backed by evidence",
            ),
        )

    def test_close_accepts_provenance_checked_completion_result_evidence(self):
        current=state()
        evidence=file_plan(path="src/chatgpt_operation/terminal.py")
        action_id=mark_complete(current,evidence)
        claim={
            "criteria":[
                {"criterion":criterion,"evidence_action_ids":[action_id]}
                for criterion in extract_acceptance_criteria(BODY)
            ]
        }
        failure=preflight_semantic_plan(
            plan=close_plan(),
            progress=None,
            completion_claim=claim,
            issue_body=BODY,
            state=current,
            repository_context=context(),
        )
        self.assertIsNone(failure)

    def test_rejects_premature_close_without_verified_coverage(self):
        failure=preflight_semantic_plan(
            plan=close_plan(),
            progress=None,
            completion_claim=None,
            issue_body=BODY,
            state=state(),
            repository_context=context(),
        )
        self.assertEqual(failure.code,"premature_close")

    def test_rejects_unverified_completion_evidence(self):
        claim={
            "criteria":[
                {"criterion":criterion,"evidence_action_ids":["missing"]}
                for criterion in extract_acceptance_criteria(BODY)
            ]
        }
        failure=preflight_semantic_plan(
            plan=close_plan(),
            progress=None,
            completion_claim=claim,
            issue_body=BODY,
            state=state(),
            repository_context=context(),
        )
        self.assertEqual(failure.code,"unverified_completion_evidence")

    def test_accepts_close_when_every_criterion_has_terminal_success_evidence(self):
        current=state()
        evidence=file_plan()
        enqueue_suspended_action(current,evidence)
        action_id=evidence.idempotency_key
        current.action_queue[action_id]["status"]="complete"
        current.execution_results[action_id]={
            "schema_version":1,
            "research_id":"issue:24",
            "action_id":action_id,
            "executor":"repository_mutation",
            "status":"pass",
            "observation":"verified",
            "retryable":False,
            "details":{},
        }
        claim={
            "criteria":[
                {"criterion":criterion,"evidence_action_ids":[action_id]}
                for criterion in extract_acceptance_criteria(BODY)
            ]
        }
        failure=preflight_semantic_plan(
            plan=close_plan(),
            progress=None,
            completion_claim=claim,
            issue_body=BODY,
            state=current,
            repository_context=context(),
        )
        self.assertIsNone(failure)


if __name__=="__main__":
    unittest.main()
