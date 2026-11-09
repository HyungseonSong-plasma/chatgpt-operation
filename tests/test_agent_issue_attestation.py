"""GitHub identity and immutable artifact attestation for agent Child receipts."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import unittest
from zipfile import ZipFile, ZIP_DEFLATED

from chatgpt_operation.controller.agent_issue_attestation import (
    ARTIFACT_PREFIX, AgentEvidenceError, verify_authenticated_child_receipt,
)
from chatgpt_operation.controller.agent_issue_partition import (
    make_assignment, make_receipt,
)

REPO="HyungseonSong-plasma/chatgpt-operation"
ACTOR="HyungseonSong-plasma"
HEAD="a"*40
RID=12001
ARTIFACT_ID=25001


def sha(data):
    return hashlib.sha256(data).hexdigest()


def evidence_zip(receipt, extra=None):
    data=io.BytesIO()
    with ZipFile(data,"w",ZIP_DEFLATED) as out:
        out.writestr(
            "agent-receipt.json",
            json.dumps({"schema_version":1,"receipt":receipt},sort_keys=True),
        )
        if extra is not None:
            out.writestr("unexpected.dat",extra)
    return data.getvalue()


def fixtures():
    assignment=make_assignment(
        repository=REPO,parent_issue=44,child_issue=123,
        agent_id="agent-a",work_id="issue:44",
        plan_sha256=sha(b"plan"),policy_sha256=sha(b"policy"),
        source_head_sha=HEAD,
        units=[{"id":"docs/example.md","input_sha256":sha(b"doc"),
                "requires":[],"gates":["attested-source"]}],
    )
    receipt=make_receipt(
        assignment,unit_id="docs/example.md",input_sha256=sha(b"doc"),
        outcome="PASS",detail={"source":"docs/example.md","sha":sha(b"doc")},
        source_run_id=RID,
    )
    raw=evidence_zip(receipt)
    run={
        "id":RID,"repository":{"full_name":REPO},
        "actor":{"login":ACTOR},
        "path":".github/workflows/samuel-agent-child-evidence.yml@refs/heads/main",
        "event":"workflow_dispatch","head_branch":"main",
        "head_sha":HEAD,"status":"completed","conclusion":"success","run_attempt":1,
    }
    artifacts={
        "total_count":1,
        "artifacts":[{
            "id":ARTIFACT_ID,"name":ARTIFACT_PREFIX+str(RID),
            "expired":False,"workflow_run":{"id":RID},
            "digest":"sha256:"+sha(raw),
        }],
    }
    return receipt,raw,run,artifacts


class GithubEvidenceFake:
    def __init__(self,run,artifacts):
        self.run=run
        self.artifacts=artifacts
        self.calls=[]

    def get(self,path,*,query=None):
        self.calls.append((path,query))
        if path==f"/actions/runs/{RID}":
            return copy.deepcopy(self.run)
        if path==f"/actions/runs/{RID}/artifacts":
            return copy.deepcopy(self.artifacts)
        raise AssertionError("unapproved GitHub read "+path)


def attest(receipt=None,raw=None,run=None,artifacts=None):
    r,bytes_,run_,arts=fixtures()
    data=r if receipt is None else receipt
    rawbytes=bytes_ if raw is None else raw
    api=GithubEvidenceFake(run_ if run is None else run,
                            arts if artifacts is None else artifacts)
    result=verify_authenticated_child_receipt(
        data,reader=api,
        fetch_artifact_zip=lambda artifact_id: rawbytes if artifact_id==ARTIFACT_ID else b"",
        repository=REPO,trusted_actor=ACTOR,
    )
    return result,api


class AgentChildAttestationTests(unittest.TestCase):
    def test_exact_run_and_artifact_return_verified_receipt_identity(self):
        r,*_=fixtures()
        proof,api=attest(r)
        self.assertTrue(proof["verified"])
        self.assertEqual(proof["receipt_id"],r["receipt_id"])
        self.assertEqual(len(api.calls),2)
        self.assertEqual(api.calls[1][1]["name"],ARTIFACT_PREFIX+str(RID))

    def test_forged_run_or_unfinished_execution_fail_closed(self):
        for key,val in (
            ("id",RID+1),("run_attempt",2),
            ("repository",{"full_name":"other/repo"}),
            ("actor",{"login":"external"}),
            ("path",".github/workflows/ci.yml"),
            ("event","pull_request"),
            ("head_branch","feature"),
            ("head_sha","b"*40),
            ("status","in_progress"),("conclusion","failure"),
        ):
            with self.subTest(key=key):
                _,_,run,_=fixtures()
                run[key]=val
                with self.assertRaisesRegex(AgentEvidenceError,"untrusted GitHub run"):
                    attest(run=run)

    def test_expired_missing_duplicate_or_forged_artifact_is_denied(self):
        for mode in ("expired","missing","duplicated","foreign_run","wrong_digest"):
            with self.subTest(mode=mode):
                _,_,_,entries=fixtures()
                if mode=="expired":
                    entries["artifacts"][0]["expired"]=True
                elif mode=="missing":
                    entries["total_count"]=0
                    entries["artifacts"]=[]
                elif mode=="duplicated":
                    entries["total_count"]=2
                elif mode=="foreign_run":
                    entries["artifacts"][0]["workflow_run"]["id"]=9999
                else:
                    entries["artifacts"][0]["digest"]="sha256:"+"f"*64
                with self.assertRaises(AgentEvidenceError):
                    attest(artifacts=entries)

    def test_tampered_zip_extra_members_or_modified_manifest_is_denied(self):
        receipt,raw,_,artifacts=fixtures()
        for corrupted in (b"not a zip",raw[:-20],evidence_zip(receipt,extra=b"oops")):
            with self.subTest(length=len(corrupted)):
                with self.assertRaises(AgentEvidenceError):
                    attest(raw=corrupted)
        modified=copy.deepcopy(receipt)
        modified["detail"]={"another":"result"}
        archive=evidence_zip(modified)
        changed=copy.deepcopy(artifacts)
        changed["artifacts"][0]["digest"]="sha256:"+sha(archive)
        with self.assertRaises(AgentEvidenceError):
            attest(raw=archive,artifacts=changed)

    def test_lossy_json_and_unexpected_workflow_are_not_accepted(self):
        r,*_=fixtures()
        with self.assertRaisesRegex(AgentEvidenceError,"unexpected evidence"):
            verify_authenticated_child_receipt(
                r,reader=GithubEvidenceFake({},{}),
                fetch_artifact_zip=lambda _:b"",
                repository=REPO,trusted_actor=ACTOR,
                approved_workflow="arbitrary.yml",
            )

if __name__=="__main__":
    unittest.main()
