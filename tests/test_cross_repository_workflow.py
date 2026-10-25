"""Foreign Issue #92 durable Controller, execution and CI failure controls."""
from __future__ import annotations

from dataclasses import replace
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from chatgpt_operation.controller.action_plan import ActionPlan
from chatgpt_operation.controller.cross_repository_issue_admission import CrossRepositoryIssueSnapshot
from chatgpt_operation.controller.cross_repository_workflow import (
    WORK_ID, TARGET, MARKER, ForeignWorkError, ForeignWorkState,
    digest, encode_ledger, decode_ledger, select_authoritative_ledger,
    from_verified_admission, reconcile_admission, plan_next_cycle,
    review_for_dispatch, record_dispatch, observe_pr_ci,validate_foreign_plan,
)
from chatgpt_operation.controller.cross_repository_execution_gateway import (
    dispatch_foreign_action, observe_foreign_execution,inspect_foreign_pr_ci,
)
from chatgpt_operation.controller.decisions import DecisionRegistry
from chatgpt_operation.controller.runtime import SamuelController,ControllerTrigger,TriggerKind
from chatgpt_operation.controller.reasoning_provider import ReasoningProviderRegistry

BASE="a"*40
ISSUE="b"*64
CRITERIA=("Pin real external SDK consumer evidence","Verify actual DTO/schema baselines")
ACCEPT_SHA=digest(list(CRITERIA))
BRANCH="samuel/92-governed-implementation"
PATH="tests/test_samuel_issue92_codeqa_proof.py"


def snapshot():
    return CrossRepositoryIssueSnapshot(
        1,WORK_ID,"HyungseonSong-plasma/chatgpt-operation",220,
        TARGET,1424293498,92,
        "https://github.com/HyungseonSong-plasma/codeQA/issues/92",
        "SDK compatibility",ISSUE,CRITERIA,40231428604,"c"*40,BASE,
        "REASONING_REQUIRED_NO_EXECUTABLE_PLAN",None,False,
    )


def future_policy(enabled=False):
    return {
        "schema_version":1,
        "policy_id":"samuel-codeqa-issue92-execution-v1",
        "enabled":enabled,"repository":TARGET,"repository_id":1424293498,
        "base_sha":BASE,"head_branch":BRANCH,
        "path_prefixes":["src/codeqa/","tests/","fixtures/python-sdk/"],
        "executor_workflow":"samuel-codeqa-issue-execute.yml",
        "merge_enabled":False,
    }


def file_plan(path=PATH,branch=BRANCH,repository=TARGET):
    return {
        "schema_version":1,"research_id":WORK_ID,"stage":"execute",
        "executor":"repository_mutation",
        "payload":{
            "schema_version":1,"repository":repository,
            "resource":"file","action":"create",
            "target":{"branch":branch,"path":path},
            "expected":{"absent":True},
            "desired":{"content":"# Verified future codeQA test fixture\n"},
            "commit_message":"test(#92): add independently reviewed contract witness",
        },
        "expected_observation":"Exact target head CI and target-owned receipt corroborate the change",
    }


def reasoning_context():
    return {
        "cross_repository_scope":{
            "verified":True,"work_id":WORK_ID,
            "issue_body_sha256":ISSUE,"target_base_sha":BASE,
        },
        "acceptance_criteria":list(CRITERIA),
        "completion_allowed":False,
        "observations":["Untrusted raw Issue body not executable"],
    }


def runner(action=None):
    def call(task,context,attempt,validation_error):
        return {
            "operation":"analyze","decision_id":None,
            "compatible_with_locked_decisions":True,
            "revision_requested":False,
            "action_plan":file_plan() if action is None else action,
        }
    return call


def decisions():
    return DecisionRegistry.load(Path("automation/samuel/decisions.json"))


def reviewed_state():
    s=from_verified_admission(snapshot())
    p=plan_next_cycle(s,reasoning_context(),registry=decisions(),
                      reasoning_runner=runner(),execution_policy=future_policy())
    return p


class DurableLedgerTests(unittest.TestCase):
    def test_admission_roundtrip_and_replayed_run_idempotency(self):
        s=from_verified_admission(snapshot())
        self.assertEqual(s.work_id,WORK_ID)
        self.assertEqual(s.phase,"reasoning_required")
        self.assertEqual(s.revision,0)
        self.assertEqual(decode_ledger(encode_ledger(s)),s)
        self.assertEqual(reconcile_admission(s,snapshot()),s)
        cid,recovered=select_authoritative_ledger([{"id":37,"body":encode_ledger(s)}])
        self.assertEqual(cid,37)
        self.assertEqual(recovered,s)

    def test_duplicate_or_untrusted_ledger_is_denied(self):
        s=from_verified_admission(snapshot())
        with self.assertRaisesRegex(ForeignWorkError,"ambiguous"):
            select_authoritative_ledger([
                {"id":1,"body":encode_ledger(s)},
                {"id":2,"body":encode_ledger(s)},
            ])
        with self.assertRaisesRegex(ForeignWorkError,"marker"):
            decode_ledger("some other GitHub Issue comment")
        raw=s.to_dict()
        raw["work_id"]="issue:92"
        with self.assertRaisesRegex(ForeignWorkError,"invalid"):
            ForeignWorkState.from_dict(raw)
        raw=s.to_dict()
        raw["action_id"]="spoofed"
        with self.assertRaisesRegex(ForeignWorkError,"orphan"):
            ForeignWorkState.from_dict(raw)

    def test_stale_issue_and_head_enter_revision_required_without_plan(self):
        s=from_verified_admission(snapshot())
        for changed in [
            replace(snapshot(),issue_body_sha256="c"*64),
            replace(snapshot(),target_base_sha="d"*40),
            replace(snapshot(),acceptance_criteria=("some other criterion",)),
        ]:
            with self.subTest(changed=changed):
                revised=reconcile_admission(s,changed)
                self.assertEqual(revised.phase,"revision_required")
                self.assertEqual(revised.last_failure,"ADMISSION_FACTS_CHANGED")
                self.assertIsNone(revised.action_plan)
                self.assertEqual(reconcile_admission(revised,changed),revised)

    def test_actual_samuel_run_cycle_foreign_branch_is_separate(self):
        ctrl=SamuelController(decisions=decisions(),
                              reasoning=ReasoningProviderRegistry(),
                              reasoning_enabled=False)
        arg=dict(
            trigger=ControllerTrigger(kind=TriggerKind.WORKFLOW_DISPATCH,ref="main"),
            comments=[],pending=[],foreign_snapshot=snapshot(),
            foreign_context=reasoning_context(),
            foreign_policy=future_policy(),
        )
        c=ctrl.run_cycle(**arg)
        self.assertEqual(c.selected_work["kind"],"foreign_issue")
        self.assertEqual(c.selected_work["work_id"],WORK_ID)
        self.assertEqual(c.issue_planning["outcome"],"reasoning_required")
        self.assertIsNone(c.execution_command)
        self.assertFalse(c.issue_planning["execution_authorized"])
        self.assertEqual(ForeignWorkState.from_dict(c.issue_planning["foreign_ledger"]).revision,0)
        with self.assertRaisesRegex(ValueError,"authenticated"):
            ctrl.run_cycle(**{**arg,"trigger":ControllerTrigger(kind=TriggerKind.ISSUES)})
        with self.assertRaisesRegex(ValueError,"verified snapshot"):
            ctrl.run_cycle(
                ControllerTrigger(kind=TriggerKind.WORKFLOW_DISPATCH),
                comments=[],pending=[],foreign_context=reasoning_context(),
            )


class ForeignPlanTests(unittest.TestCase):
    def test_real_typed_provider_plan_waits_for_review(self):
        s=reviewed_state()
        self.assertEqual(s.phase,"review_required")
        self.assertEqual(s.revision,1)
        self.assertIsNotNone(s.action_id)
        self.assertIsNone(s.receipt)
        self.assertEqual(s.action_id,ActionPlan.from_dict(s.action_plan).idempotency_key)
        with self.assertRaisesRegex(ForeignWorkError,"approved"):
            review_for_dispatch(s,execution_policy=future_policy(False),
                                approved_action_id=s.action_id,expected_revision=1)
        advanced=review_for_dispatch(s,execution_policy=future_policy(True),
                                     approved_action_id=s.action_id,expected_revision=1)
        self.assertEqual(advanced.phase,"dispatch_ready")
        self.assertEqual(advanced.revision,2)
        with self.assertRaisesRegex(ForeignWorkError,"stale"):
            review_for_dispatch(s,execution_policy=future_policy(True),
                                approved_action_id=s.action_id,expected_revision=2)

    def test_untrusted_issue_text_never_authorizes_execution(self):
        s=from_verified_admission(snapshot())
        with self.assertRaisesRegex(ForeignWorkError,"scope"):
            plan_next_cycle(s,{**reasoning_context(),
                               "cross_repository_scope":{"verified":True,"work_id":"issue:92"}},
                            registry=decisions(),reasoning_runner=runner(),
                            execution_policy=future_policy())
        with self.assertRaisesRegex(ForeignWorkError,"scope"):
            plan_next_cycle(s,{**reasoning_context(),"completion_allowed":True},
                            registry=decisions(),reasoning_runner=runner(),
                            execution_policy=future_policy())
        self.assertEqual(plan_next_cycle(
            s,reasoning_context(),registry=decisions(),reasoning_runner=None,
            execution_policy=future_policy(),
        ),s)

    def test_disallowed_repositories_branches_and_file_paths_fail(self):
        pol=future_policy(True)
        for raw in [
            file_plan(repository="HyungseonSong-plasma/chatgpt-operation"),
            file_plan(path=".github/workflows/bad.yml"),
            file_plan(path="src/../.github/bad.yml"),
            file_plan(path="automation/samuel/policy.json"),
            file_plan(path="src/codeqa/secret.py",branch="main"),
            file_plan(path="README.md"),
        ]:
            with self.subTest(raw=raw):
                with self.assertRaises((ForeignWorkError,ValueError)):
                    validate_foreign_plan(ActionPlan.from_dict(raw),pol)
        with self.assertRaisesRegex(ForeignWorkError,"approved"):
            validate_foreign_plan(ActionPlan.from_dict(file_plan()),future_policy(False))

    def test_source_main_and_merges_never_accepted(self):
        pol=future_policy(True)
        pol["merge_enabled"]=True
        with self.assertRaisesRegex(ForeignWorkError,"approved"):
            validate_foreign_plan(ActionPlan.from_dict(file_plan()),pol)
        raw=file_plan()
        raw["executor"]="github_native"
        raw["payload"]={"action":"merge_pr","repository":TARGET}
        with self.assertRaisesRegex(ForeignWorkError,"approved"):
            validate_foreign_plan(ActionPlan.from_dict(raw),future_policy(True))


class CIRevisionTests(unittest.TestCase):
    def fake_dispatched(self):
        s=reviewed_state()
        p=review_for_dispatch(s,execution_policy=future_policy(True),
                              approved_action_id=s.action_id,expected_revision=s.revision)
        return record_dispatch(p,{"workflow_run_id":900,"ref":"main",
                                   "correlation_id":p.action_id},expected_revision=p.revision)

    def fake_pr(self,sha="d"*40):
        return {
            "number":114,"state":"open","draft":True,"merged":False,
            "base":{"ref":"main"},
            "head":{"sha":sha,"ref":BRANCH,"repo":{"full_name":TARGET}},
        }

    def runs(self,statuses,sha="d"*40):
        return [
            {"id":200+i,"path":".github/workflows/"+name,
             "head_sha":sha,"head_branch":BRANCH,"event":"pull_request",
             "status":"completed" if conclusion is not None else "in_progress",
             "conclusion":conclusion}
            for i,(name,conclusion) in enumerate(statuses)
        ]

    def test_ci_pending_failure_and_exact_success_are_distinct(self):
        s=self.fake_dispatched()
        names=("layout.yml","pinned-python-sdk.yml")
        one=self.runs([("layout.yml","success")])
        pending=observe_pr_ci(s,pr=self.fake_pr(),runs=one,required_workflows=names)
        self.assertEqual(pending.phase,"ci_pending")
        failed=observe_pr_ci(pending,pr=self.fake_pr(),runs=self.runs([
            ("layout.yml","success"),("pinned-python-sdk.yml","failure")
        ]),required_workflows=names)
        self.assertEqual(failed.phase,"revision_required")
        self.assertEqual(failed.last_failure,"EXACT_HEAD_CI_FAILURE")
        success=observe_pr_ci(pending,pr=self.fake_pr(),runs=self.runs([
            ("layout.yml","success"),("pinned-python-sdk.yml","success")
        ]),required_workflows=names)
        self.assertEqual(success.phase,"ci_verified")
        self.assertEqual(len(success.ci_evidence),2)
        self.assertIsNone(success.last_failure)

    def test_wrong_sha_merged_pr_and_skip_do_not_pass(self):
        s=self.fake_dispatched()
        p=self.fake_pr()
        p["merged"]=True
        with self.assertRaisesRegex(ForeignWorkError,"untrusted"):
            observe_pr_ci(s,pr=p,runs=[],required_workflows=("layout.yml",))
        status=observe_pr_ci(s,pr=self.fake_pr(),runs=self.runs([
            ("layout.yml","skipped")
        ]),required_workflows=("layout.yml",))
        self.assertEqual(status.phase,"revision_required")
        stale=observe_pr_ci(s,pr=self.fake_pr(),runs=self.runs([
            ("layout.yml","success")
        ],sha="c"*40),required_workflows=("layout.yml",))
        self.assertEqual(stale.phase,"ci_pending")

    def test_execution_gateway_denies_missing_review_and_wrong_target(self):
        s=reviewed_state()
        class Transport:
            repository=TARGET
            def get(self,path,**kwargs):
                raise AssertionError("disabled policy should fail before network")
        with self.assertRaisesRegex(ForeignWorkError,"unauthorized"):
            dispatch_foreign_action(s,target_transport=Transport(),
                                    execution_policy=future_policy(True),
                                    expected_revision=s.revision)
        p=review_for_dispatch(s,execution_policy=future_policy(True),
                              approved_action_id=s.action_id,expected_revision=s.revision)
        class WrongTransport(Transport):
            repository="HyungseonSong-plasma/chatgpt-operation"
        with self.assertRaisesRegex(ForeignWorkError,"bound"):
            dispatch_foreign_action(p,target_transport=WrongTransport(),
                                    execution_policy=future_policy(True),
                                    expected_revision=p.revision)

    def test_execution_gateway_rejects_uninstalled_target_executor(self):
        s=reviewed_state()
        p=review_for_dispatch(s,execution_policy=future_policy(True),
                              approved_action_id=s.action_id,expected_revision=s.revision)
        class Target:
            repository=TARGET
            def get(self,path,**kwargs):
                if path=="/git/ref/heads/main":
                    return {"object":{"sha":BASE}}
                if path.startswith("/actions/workflows/"):
                    return {"path":".github/workflows/wrong.yml","state":"active"}
                raise AssertionError(path)
        with self.assertRaisesRegex(ForeignWorkError,"not installed"):
            dispatch_foreign_action(p,target_transport=Target(),
                                    execution_policy=future_policy(True),
                                    expected_revision=p.revision)

    def test_target_owned_receipt_and_exact_head_required_for_ci(self):
        s=self.fake_dispatched()
        pending=replace(s,phase="ci_pending")
        class Target:
            repository=TARGET
            def get(self,path,**kwargs):
                if path.startswith("/pulls/"):
                    return CIRevisionTests().fake_pr()
                if path=="/actions/runs":
                    return {"workflow_runs":CIRevisionTests().runs([
                        ("layout.yml","success")
                    ])}
                raise AssertionError(path)
        trusted={"status":"EXECUTED_DRAFT_PR","work_id":WORK_ID,
                 "action_id":s.action_id,"base_sha":BASE,
                 "source_run_id":s.admission_run_id,
                 "merge_performed":False,"pr_number":114,
                 "head_sha":"d"*40}
        result=inspect_foreign_pr_ci(pending,target_transport=Target(),
                                     target_receipt=trusted,required_workflows=("layout.yml",))
        self.assertEqual(result.phase,"ci_verified")
        for k,v in [("action_id","fake"),("source_run_id",12),("merge_performed",True)]:
            with self.subTest(k=k):
                with self.assertRaisesRegex(ForeignWorkError,"receipt"):
                    inspect_foreign_pr_ci(pending,target_transport=Target(),
                        target_receipt={**trusted,k:v},required_workflows=("layout.yml",))
