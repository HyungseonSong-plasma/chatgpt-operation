"""Child worker: exact run authentication, pinned source, scoped append."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chatgpt_operation.controller.agent_issue_partition import (
    child_issue_body, make_assignment, make_receipt, receipt_comment_body,
)
from chatgpt_operation.controller.agent_issue_source import (
    AgentSourceError, build_readonly_document_receipt,
)
from chatgpt_operation.controller.agent_issue_worker import (
    AgentWorkerError, produce_child_manifest, publish_child_manifest,
    verified_worker_identity,
)
from chatgpt_operation.github.actions_runtime import ActionsApiError

REPO="HyungseonSong-plasma/chatgpt-operation"
ACTOR="HyungseonSong-plasma"
SHA="a"*40
RUN=12021
DOC=b"# title\n[a](../README.md)\n[b](page.md)\n"


def hash_(x):
    return hashlib.sha256(x).hexdigest()


def assignment():
    return make_assignment(
        repository=REPO,parent_issue=44,child_issue=501,
        agent_id="agent-001",work_id="issue:44",
        plan_sha256=hash_(b"plan"),policy_sha256=hash_(b"policy"),
        source_head_sha=SHA,
        units=[{"id":"docs/a.md","input_sha256":hash_(DOC),
                "requires":[],"gates":["attested-source"]}],
    )


def env():
    return {
        "GITHUB_ACTIONS":"true","GITHUB_REPOSITORY":REPO,
        "GITHUB_EVENT_NAME":"workflow_dispatch",
        "GITHUB_REF":"refs/heads/main",
        "GITHUB_ACTOR":ACTOR,"GITHUB_RUN_ID":str(RUN),
        "GITHUB_RUN_ATTEMPT":"1","GITHUB_SHA":SHA,
    }


def run():
    return {
        "id":RUN, "run_attempt":1,
        "actor":{"login":ACTOR},
        "repository":{"full_name":REPO},
        "path":".github/workflows/samuel-agent-child-evidence.yml",
        "head_sha":SHA,"head_branch":"main","event":"workflow_dispatch",
        "status":"in_progress",
    }


def issue():
    a=assignment()
    return {
        "id":100501,"number":501,
        "url":f"https://api.github.com/repos/{REPO}/issues/501",
        "body":child_issue_body(a),"labels":[],"state":"open",
    }


class FakeGH:
    def __init__(self):
        self.run=run()
        self.issue=issue()
        self.comments=[]
        self.calls=[]
        self.lose_ack=False

    def get(self,path,*,query=None):
        self.calls.append(("GET",path))
        if path==f"/actions/runs/{RUN}":
            return copy.deepcopy(self.run)
        if path=="/issues/501":
            return copy.deepcopy(self.issue)
        if path=="/issues/501/comments":
            page=int(query["page"])
            return copy.deepcopy(self.comments[(page-1)*100:page*100])
        raise AssertionError("unexpected Github GET "+path)

    def request(self,method,path,*,payload=None):
        self.calls.append((method,path))
        if method!="POST" or path!="/issues/501/comments":
            raise AssertionError("worker tried to write outside Child")
        c={
            "id":1024+len(self.comments),"body":payload["body"],
            "user":{"login":"github-actions[bot]"},
            "created_at":"2026-11-09T00:00:00Z",
            "updated_at":"2026-11-09T00:00:00Z",
        }
        self.comments.append(c)
        if self.lose_ack:
            self.lose_ack=False
            raise ActionsApiError("simulated network loss")
        return 201,copy.deepcopy(c)


def receipt():
    return make_receipt(
        assignment(),unit_id="docs/a.md",input_sha256=hash_(DOC),
        outcome="PASS",detail={"unit":"docs/a.md"},source_run_id=RUN,
    )


class AgentChildWorkerTests(unittest.TestCase):
    def test_exact_main_workflow_run_accepted(self):
        api=FakeGH()
        self.assertEqual(verified_worker_identity(api,env()),(RUN,SHA))
        self.assertEqual(api.calls,[("GET",f"/actions/runs/{RUN}")])

    def test_untrusted_workflow_or_approver_is_rejected(self):
        for key,val in (
            ("GITHUB_REF","refs/heads/feature"),
            ("GITHUB_ACTOR","untrusted"),
            ("GITHUB_REPOSITORY","foreign/repo"),
            ("GITHUB_RUN_ATTEMPT","2"),
        ):
            with self.subTest(field=key):
                fake=FakeGH()
                changed=env()
                changed[key]=val
                with self.assertRaises(AgentWorkerError):
                    verified_worker_identity(fake,changed)
        api=FakeGH()
        api.run["path"]=".github/workflows/ci.yml"
        with self.assertRaisesRegex(AgentWorkerError,"not approved"):
            verified_worker_identity(api,env())

    def test_document_hash_matches_reviewed_checkout_and_enumerates_links(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/"docs").mkdir()
            (root/"docs/a.md").write_bytes(DOC)
            result=build_readonly_document_receipt(
                assignment(),unit_id="docs/a.md",run_id=RUN,
                source_sha=SHA,root=root,
            )
            self.assertEqual(result["source_run_id"],RUN)
            self.assertEqual(result["detail"]["line_count"],3)
            self.assertEqual(
                [x["target"] for x in result["detail"]["links"]],
                ["../README.md","page.md"],
            )
            with patch(
                "chatgpt_operation.controller.agent_issue_worker._assignment_for_child",
                return_value=(assignment(),[assignment()]),
            ):
                manifest=produce_child_manifest(
                    FakeGH(),environment=env(),child_issue=501,
                    unit_id="docs/a.md",source_root=root,
                )
            self.assertEqual(manifest["schema_version"],1)
            self.assertEqual(manifest["receipt"],result)

    def test_untrusted_or_changed_source_bytes_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/"docs").mkdir()
            (root/"docs/a.md").write_bytes(b"modified\n")
            with self.assertRaisesRegex(AgentSourceError,"source content SHA"):
                build_readonly_document_receipt(
                    assignment(),unit_id="docs/a.md",run_id=RUN,
                    source_sha=SHA,root=root,
                )
            with self.assertRaisesRegex(AgentSourceError,"only scoped"):
                build_readonly_document_receipt(
                    assignment(),unit_id="../secrets.md",run_id=RUN,
                    source_sha=SHA,root=root,
                )
            with self.assertRaisesRegex(AgentSourceError,"workflow HEAD"):
                build_readonly_document_receipt(
                    assignment(),unit_id="docs/a.md",run_id=RUN,
                    source_sha="b"*40,root=root,
                )

    def test_authenticated_worker_appends_only_its_child(self):
        api=FakeGH()
        with patch(
            "chatgpt_operation.controller.agent_issue_worker._assignment_for_child",
            return_value=(assignment(),[assignment()]),
        ):
            manifest={"schema_version":1,"receipt":receipt()}
            applied=publish_child_manifest(
                api,environment=env(),child_issue=501,manifest=manifest,
            )
            self.assertEqual(applied["status"],"COMMITTED_APPEND")
            self.assertFalse(applied["parent_state_patch"])
            repeated=publish_child_manifest(
                api,environment=env(),child_issue=501,manifest=manifest,
            )
        self.assertEqual(repeated["status"],"ALREADY_PRESENT")
        self.assertEqual(
            [x for x in api.calls if x[0] in ("POST","PATCH")],
            [("POST","/issues/501/comments")],
        )

    def test_accepted_post_with_lost_ack_recovers_without_second_post(self):
        api=FakeGH()
        api.lose_ack=True
        with patch(
            "chatgpt_operation.controller.agent_issue_worker._assignment_for_child",
            return_value=(assignment(),[assignment()]),
        ):
            final=publish_child_manifest(
                api,environment=env(),child_issue=501,
                manifest={"schema_version":1,"receipt":receipt()},
            )
        self.assertEqual(final["status"],"COMMITTED_APPEND")
        self.assertEqual(len(api.comments),1)
        self.assertEqual(
            len([x for x in api.calls if x[0]=="POST"]),1,
        )

    def test_other_agent_or_parent_number_never_mutated(self):
        api=FakeGH()
        with patch(
            "chatgpt_operation.controller.agent_issue_worker._assignment_for_child",
            return_value=(assignment(),[assignment()]),
        ):
            with self.assertRaisesRegex(AgentWorkerError,"invalid requested Child"):
                publish_child_manifest(
                    api,environment=env(),child_issue=44,
                    manifest={"schema_version":1,"receipt":receipt()},
                )
            wrong=copy.deepcopy(receipt())
            wrong["child_issue"]=502
            with self.assertRaisesRegex(Exception,"digest"):
                publish_child_manifest(
                    api,environment=env(),child_issue=501,
                    manifest={"schema_version":1,"receipt":wrong},
                )
        self.assertEqual([x for x in api.calls if x[0]=="POST"],[])

    def test_producer_and_parent_workflows_are_separate_and_scoped(self):
        producer=Path(
            ".github/workflows/samuel-agent-child-evidence.yml"
        ).read_text(encoding="utf-8")
        parent=Path(
            ".github/workflows/samuel-agent-child-parent-audit.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("group: samuel-agent-child-",producer)
        self.assertIn("queue: max",producer)
        self.assertIn("issues: write",producer)
        self.assertNotIn("gh api --method PATCH",producer)
        self.assertNotIn("issues: write",parent)
        self.assertIn("issues: read",parent)
        self.assertIn("workflow_dispatch:",producer)
        self.assertIn("workflow_dispatch:",parent)
        self.assertNotIn("schedule:",producer)
        self.assertNotIn("schedule:",parent)


if __name__=="__main__":
    unittest.main()
