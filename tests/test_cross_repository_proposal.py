"""Production-shaped Issue #92 provider proposal preflight and review tests."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import runpy
import sys
import unittest
from urllib.error import HTTPError

from chatgpt_operation.controller.action_plan import ActionPlan
from chatgpt_operation.controller.cross_repository_issue_admission import CrossRepositoryIssueSnapshot
from chatgpt_operation.controller.cross_repository_workflow import (
    ForeignWorkError, ForeignWorkState, digest, from_verified_admission,
)
from chatgpt_operation.controller.cross_repository_proposal import (
    PROPOSAL_PATH, PROPOSAL_BRANCH, ProposalPreflightError,
    proposed_reasoning_context, verify_proposal_preflight, verify_proposed_review,
)
from chatgpt_operation.controller.decisions import DecisionRegistry
from chatgpt_operation.controller.reasoning_provider import ReasoningProviderRegistry
from chatgpt_operation.controller.runtime import SamuelController, ControllerTrigger, TriggerKind


TARGET="HyungseonSong-plasma/codeQA"
SOURCE="HyungseonSong-plasma/chatgpt-operation"
BASE="f7859c7f742ba55025bf1633ef7438d18e8a9416"
ISSUE="4473f4ea46a6d9aacaa2b8933de99a7e1ff778a4083dab316ab4fc3cc1115b3e"
CRITERIA=(
    "Obtain and pin real external SDK consumer artifacts and type checker",
    "Verify public DTO/ORM schema baselines without false PASS",
)


def snapshot():
    return CrossRepositoryIssueSnapshot(
        1,f"github:{TARGET}:issue:92",SOURCE,220,
        TARGET,1424293498,92,
        f"https://github.com/{TARGET}/issues/92",
        "Pinned SDK/public API contract",ISSUE,CRITERIA,
        40237333798,"2"*40,BASE,"REASONING_REQUIRED_NO_EXECUTABLE_PLAN",
        None,False,
    )


def policy():
    return json.loads(
        Path("automation/samuel/codeqa-issue92-execution-candidate-v1.json").read_text()
    )


def work():
    return from_verified_admission(snapshot())


def context():
    return {
        "cross_repository_scope":{
            "verified":True,
            "work_id":f"github:{TARGET}:issue:92",
            "target_repository":TARGET,
            "target_base_sha":BASE,
            "issue_body_sha256":ISSUE,
        },
        "acceptance_criteria":list(CRITERIA),
        "completion_allowed":False,
        "observations":["Verified facts, raw remote Issue commands omitted"],
    }


def valid_plan():
    return {
        "schema_version":1,"research_id":f"github:{TARGET}:issue:92",
        "stage":"execute","executor":"repository_mutation",
        "payload":{
            "schema_version":1,"repository":TARGET,
            "resource":"file","action":"create",
            "target":{"path":PROPOSAL_PATH,"branch":PROPOSAL_BRANCH},
            "expected":{"absent":True},
            "desired":{"content":"def test_unverified_real_sdk_baseline_is_explicit():\n    assert 'NOT_EVALUATED' != 'PASS'\n"},
            "commit_message":"test(#92): review SDK evidence failure policy",
        },
        "expected_observation":"Target Draft PR exact HEAD required checks",
        "decision_risk":None,
    }


class DummyProvider:
    name="test-boundary"
    def __init__(self, result):
        self.result=result
        self.calls=[]
    def reason(self, *, task, context, attempt, validation_error):
        self.calls.append((task,context,attempt,validation_error))
        return {
            "operation":"analyze",
            "decision_id":None,
            "compatible_with_locked_decisions":True,
            "revision_requested":False,
            "action_plan":self.result,
            "blocker":None,
            "progress":None,
            "completion_claim":None,
        }


def proposal_cycle(proposed_plan):
    before=work()
    ctx=proposed_reasoning_context(context(),snapshot())
    provider=DummyProvider(proposed_plan)
    controller=SamuelController(
        decisions=DecisionRegistry.load(Path("automation/samuel/decisions.json")),
        reasoning=ReasoningProviderRegistry(provider=provider),
        reasoning_enabled=True,
    )
    cycle=controller.run_cycle(
        ControllerTrigger(kind=TriggerKind.WORKFLOW_DISPATCH,
                          head_sha="2"*40,ref="main"),
        comments=[],pending=[],
        foreign_snapshot=snapshot(),foreign_context=ctx,
        foreign_ledger=before,foreign_policy=policy(),
    )
    return before,ForeignWorkState.from_dict(cycle.issue_planning["foreign_ledger"]),provider


class ForeignProposalPreflightTests(unittest.TestCase):
    def test_real_repin_and_single_empty_review_target_pass(self):
        verify_proposal_preflight(
            work(),snapshot(),policy(),target_main_sha=BASE,candidate_absent=True,
        )
        ctx=proposed_reasoning_context(context(),snapshot())
        self.assertFalse(ctx["completion_allowed"])
        self.assertEqual(len(ctx["execution_contracts"]),1)
        self.assertEqual(ctx["execution_contracts"][0]["payload"]["target"]["path"],PROPOSAL_PATH)
        self.assertTrue(ctx["verified_target_file_precondition"]["absent"])

    def test_mismatch_prior_ledger_or_target_file_prevents_provider_call(self):
        for kwargs in [
            {"target_main_sha":"0"*40},
            {"candidate_absent":False},
            {"state":replace(work(),phase="review_required")},
            {"state":replace(work(),issue_sha="a"*64)},
            {"state":replace(work(),action_id="a"*64)},
            {"state":None},
        ]:
            with self.subTest(kwargs=kwargs):
                state=kwargs.get("state",work())
                with self.assertRaises(ProposalPreflightError):
                    verify_proposal_preflight(
                        state,snapshot(),policy(),
                        target_main_sha=kwargs.get("target_main_sha",BASE),
                        candidate_absent=kwargs.get("candidate_absent",True),
                    )

    def test_disabled_write_policy_must_remain_exact_for_preview(self):
        for change in [
            {"enabled":True},
            {"path_prefixes":["src/"]},
            {"merge_enabled":True},
            {"base_sha":"0"*40},
            {"head_branch":"main"},
            {"required_workflows":["layout.yml"]},
            {"repository":"some-other-repository"},
        ]:
            with self.subTest(change=change):
                p={**policy(),**change}
                with self.assertRaisesRegex(ProposalPreflightError,"candidate policy"):
                    verify_proposal_preflight(
                        work(),snapshot(),p,target_main_sha=BASE,candidate_absent=True,
                    )

    def test_real_controller_compiles_valid_provider_action_to_review_only(self):
        before,after,provider=proposal_cycle(valid_plan())
        self.assertEqual(after.phase,"review_required")
        self.assertEqual(after.revision,before.revision+1)
        self.assertEqual(after.action_id,ActionPlan.from_dict(after.action_plan).idempotency_key)
        self.assertIsNone(after.receipt)
        self.assertIsNone(after.target_pr)
        self.assertEqual(len(provider.calls),1)
        self.assertEqual(provider.calls[0][1]["execution_contracts"][0]["payload"]["target"]["path"],PROPOSAL_PATH)
        verify_proposed_review(before,after,policy())
        self.assertFalse(policy()["enabled"])

    def test_no_provider_action_remains_non_executable(self):
        before,after,provider=proposal_cycle(None)
        self.assertEqual(after.phase,"reasoning_required")
        self.assertIsNone(after.action_plan)
        self.assertIsNone(after.action_id)
        verify_proposed_review(before,after,policy())

    def test_semantically_valid_but_out_of_contract_model_plan_denied(self):
        for change in [
            {"path":"src/codeqa/evaluation/other.py"},
            {"path":"tests/test_samuel_issue92_other.py"},
            {"branch":"main"},
        ]:
            with self.subTest(change=change):
                p=valid_plan()
                p["payload"]["target"].update(change)
                try:
                    before,after,_=proposal_cycle(p)
                except (ForeignWorkError,ValueError):
                    continue
                with self.assertRaises(ProposalPreflightError):
                    verify_proposed_review(before,after,policy())

    def test_oversize_or_risky_model_action_fails_closed(self):
        p=valid_plan()
        p["payload"]["desired"]["content"]="x"*33000
        with self.assertRaisesRegex(ForeignWorkError,"exceeds"):
            proposal_cycle(p)
        p=valid_plan()
        p["decision_risk"]={"impact":0.1,"uncertainty":0.1,"irreversibility":0.1}
        with self.assertRaises((ForeignWorkError,ValueError)):
            proposal_cycle(p)

    def test_untrusted_output_cannot_fake_completion_or_execution(self):
        before,after,_=proposal_cycle(valid_plan())
        for p in [
            replace(after,phase="dispatch_ready"),
            replace(after,phase="ci_verified"),
            replace(after,receipt={"workflow_run_id":4}),
            replace(after,base_sha="e"*40),
        ]:
            with self.subTest(phase=p.phase),self.assertRaises(ProposalPreflightError):
                verify_proposed_review(before,p,policy())

    def test_target_file_get_treats_only_http_404_as_absent(self):
        script_dir=Path(".github/scripts").resolve()
        sys.path.insert(0,str(script_dir))
        try:
            scope=runpy.run_path(
                str(script_dir/"samuel_codeqa_foreign_cycle.py"),
                run_name="test_foreign_proposal",
            )
        finally:
            sys.path.pop(0)
        checker=scope["_target_file_is_absent"]
        class FakeTarget:
            def __init__(self,status):
                self.status=status
                self.calls=[]
            def get(self,path):
                self.calls.append(path)
                if self.status is not None:
                    raise HTTPError(path,self.status,"simulated",None,None)
                return {"sha":"untrusted-existing-file"}
        for status,expected in [(404,True),(None,False)]:
            fake=FakeTarget(status)
            self.assertEqual(checker(fake,BASE),expected)
            self.assertIn(PROPOSAL_PATH,fake.calls[0])
            self.assertIn(BASE,fake.calls[0])
        for status in [401,403,500]:
            with self.subTest(status=status),self.assertRaises(HTTPError):
                checker(FakeTarget(status),BASE)
