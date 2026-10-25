"""Adversarial owner-scheduled ChatGPT ingress, no OpenAI API key or writes."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import unittest

from chatgpt_operation.controller.action_plan import ActionPlan
from chatgpt_operation.controller.cross_repository_issue_admission import (
    extract_target_issue_acceptance,
)
from chatgpt_operation.controller.cross_repository_workflow import (
    ForeignWorkState, TARGET, SOURCE, WORK_ID, digest,
)
from chatgpt_operation.controller.cross_repository_proposal import (
    PROPOSAL_PATH, PROPOSAL_BRANCH,
)
from chatgpt_operation.controller.chatgpt_scheduled_proposal import (
    COMMENT_MARKER, OWNER_ID, ScheduledProposalError,
    parse_owner_proposal, review_owner_proposal,
)

POLICY=json.loads(Path("automation/samuel/codeqa-issue92-execution-candidate-v1.json").read_text())
BASE=POLICY["base_sha"]
BODY=(
    "## Deferred from B-scoped v0.2 acceptance: #70 and #71\n\n"
    "### Acceptance\n"
    "- Pin real SDK and verifier hash\n"
    "- Require independent public DTO and migration baseline\n"
    "\n### Existing partial deliverables\n"
    "- NOT a verified public API consumer\n"
)
ISSUE_SHA=sha256(BODY.encode()).hexdigest()
CRITERIA=extract_target_issue_acceptance(BODY)


def action(path=PROPOSAL_PATH,branch=PROPOSAL_BRANCH):
    return {
        "schema_version":1,
        "research_id":WORK_ID,
        "stage":"execute",
        "executor":"repository_mutation",
        "payload":{
            "schema_version":1,
            "repository":TARGET,
            "resource":"file",
            "action":"create",
            "target":{"path":path,"branch":branch},
            "expected":{"absent":True},
            "desired":{"content":
                "def test_external_sdk_evidence_cannot_be_assumed():\n"
                "    status = 'NOT_EVALUATED'\n"
                "    assert status != 'PASS'\n"},
            "commit_message":"test(#92): propose SDK evidence conformance guard",
        },
        "expected_observation":"Draft PR HEAD with independently observed CI",
        "decision_risk":None,
    }


def before():
    return ForeignWorkState(
        WORK_ID,ISSUE_SHA,BASE,digest(list(CRITERIA)),2,
        "reasoning_required",40237333798,
    )


def message(plan=None,revision=2,sha=ISSUE_SHA,base=BASE):
    data={
        "schema_version":1,
        "work_id":WORK_ID,
        "ledger_revision":revision,
        "target_base_sha":base,
        "issue_sha256":sha,
        "action_plan":plan if plan is not None else action(),
    }
    return "<!-- samuel-chatgpt-proposal-v1 -->\n```json\n"+json.dumps(data,sort_keys=True)+"\n```"


def params():
    return {
        "source_run":{
            "id":987654,
            "event":"issue_comment",
            "path":".github/workflows/samuel-chatgpt-proposal-ingress.yml",
            "head_branch":"main","head_sha":"c"*40,
            "repository":{"full_name":SOURCE},
            "actor":{"login":"HyungseonSong-plasma"},
        },
        "source_main_sha":"c"*40,
        "source_issue":{
            "number":220,"state":"open",
            "url":"https://api.github.com/repos/"+SOURCE+"/issues/220",
            "user":{"login":"HyungseonSong-plasma"},
        },
        "source_comment":{
            "id":444,
            "issue_url":"https://api.github.com/repos/"+SOURCE+"/issues/220",
            "user":{"login":"HyungseonSong-plasma","id":OWNER_ID},
            "body":message(),
        },
        "event_comment_id":444,
        "previous":before(),
        "target_issue":{
            "number":92,"state":"open",
            "url":"https://api.github.com/repos/"+TARGET+"/issues/92",
            "html_url":"https://github.com/"+TARGET+"/issues/92",
            "title":"Naming v0.3 SDK/public compatibility",
            "body":BODY,
        },
        "target_main_sha":BASE,
        "policy":POLICY,
        "candidate_absent":True,
    }


class ChatGPTProposalTests(unittest.TestCase):
    def test_valid_authenticated_owner_comment_stores_only_review_state(self):
        p=params()
        a=review_owner_proposal(**p)
        self.assertEqual(a.phase,"review_required")
        self.assertEqual(a.revision,3)
        self.assertEqual(a.action_id,ActionPlan.from_dict(action()).idempotency_key)
        self.assertEqual(a.action_plan["payload"]["target"]["path"],PROPOSAL_PATH)
        self.assertIsNone(a.receipt)
        self.assertIsNone(a.target_pr)
        self.assertFalse(a.ci_evidence)
        self.assertFalse(POLICY["enabled"])

    def test_parsing_requires_exact_leading_marker_closed_json_and_fields(self):
        for body in [
            "Please run "+message(),
            message()+"\nextra",
            COMMENT_MARKER+"\njson",
            message().replace('"schema_version": 1','"schema_version": 2'),
            message().replace('"work_id": "'+WORK_ID+'"','"work_id": "issue:92"'),
        ]:
            with self.subTest(body=body[:40]),self.assertRaises(ScheduledProposalError):
                parse_owner_proposal(body)

    def test_fake_actor_event_and_source_workflow_denied(self):
        for changed in [
            {"source_run":{"event":"workflow_dispatch"}},
            {"source_run":{"path":".github/workflows/samuel-codeqa-foreign-cycle.yml"}},
            {"source_run":{"head_branch":"develop"}},
            {"source_run":{"head_sha":"d"*40}},
            {"source_run":{"actor":{"login":"random"}}},
            {"source_comment":{"user":{"login":"attacker","id":123}}},
            {"source_comment":{"id":445}},
            {"source_comment":{"issue_url":"https://api.github.com/repos/"+TARGET+"/issues/92"}},
            {"source_issue":{"state":"closed"}},
        ]:
            p=params()
            for key,fields in changed.items():
                p[key].update(fields)
            with self.subTest(changed=changed),self.assertRaisesRegex(
                ScheduledProposalError,"attestation"):
                review_owner_proposal(**p)

    def test_stale_revision_base_issue_or_missing_file_denied(self):
        for changed in [
            {"candidate_absent":False},
            {"target_main_sha":"e"*40},
            {"previous":{"phase":"review_required"}},
            {"previous":{"base_sha":"e"*40}},
            {"previous":{"action_id":"f"*64}},
            {"target_issue":{"body":BODY+"\n- New unapproved requirement"}},
            {"policy":{"enabled":True}},
        ]:
            p=params()
            for key,value in changed.items():
                if isinstance(value,dict):
                    p[key]=dict(p[key],**value) if isinstance(p[key],dict) else p[key]
                    if key=="previous":
                        from dataclasses import replace
                        p[key]=replace(before(),**value)
                else:
                    p[key]=value
            with self.subTest(changed=changed),self.assertRaises(ScheduledProposalError):
                review_owner_proposal(**p)

    def test_owner_comment_binds_expected_revision_issue_sha_and_base(self):
        for body in [
            message(revision=0),message(sha="a"*64),
            message(base="b"*40),
        ]:
            p=params()
            p["source_comment"]["body"]=body
            with self.subTest(body=body[:65]),self.assertRaisesRegex(
                ScheduledProposalError,"stale"):
                review_owner_proposal(**p)

    def test_unapproved_code_file_policy_or_merge_is_rejected(self):
        for dangerous in [
            action(path=".github/workflows/bad.yml"),
            action(path="src/codeqa/governance/unsafe.py"),
            action(path="tests/test_samuel_issue92_other.py"),
            action(branch="main"),
        ]:
            p=params()
            p["source_comment"]["body"]=message(dangerous)
            with self.subTest(path=dangerous["payload"]["target"]),self.assertRaises(
                ScheduledProposalError
            ):
                review_owner_proposal(**p)

    def test_no_external_model_execution_occurs_during_ingress(self):
        import inspect
        from chatgpt_operation.controller import chatgpt_scheduled_proposal
        source=inspect.getsource(chatgpt_scheduled_proposal.review_owner_proposal)
        self.assertNotIn("OpenAIReasoningProvider",source)
        self.assertNotIn("dispatch_foreign_action",source)
        self.assertNotIn("merge_pull_request",source)
