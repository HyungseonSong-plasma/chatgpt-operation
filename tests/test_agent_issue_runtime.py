"""Authenticated Child Issue readback, pagination, parent-only reduction."""
from __future__ import annotations

import copy
import unittest

from chatgpt_operation.controller.agent_issue_runtime import (
    read_stable_child_comments, reduce_verified_parent_children,
)
from chatgpt_operation.controller.agent_issue_partition import AgentIssueError
from chatgpt_operation.controller.agent_issue_partition import (
    child_issue_body, make_assignment, make_receipt, receipt_comment_body,
)

import hashlib

REPO = "HyungseonSong-plasma/chatgpt-operation"
AUTHOR = "github-actions[bot]"


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def setup_agents(n=3, units_each=2):
    assignments = []
    for i in range(n):
        units = [
            {"id": f"scan-{j}", "input_sha256": sha(f"input/{i}/{j}"),
             "requires": [] if j == 0 else [j-1],
             "gates": ["independent-evidence"]}
            for j in range(units_each)
        ]
        assignments.append(make_assignment(
            repository=REPO, parent_issue=400, child_issue=1000+i,
            agent_id=f"agent-{i:02}", work_id="issue:400",
            plan_sha256=sha("approved-plan"), policy_sha256=sha("approved-policy"),
            source_head_sha="a"*40, units=units,
        ))
    return assignments


def issue(a):
    return {
        "number": a["child_issue"], "state": "open",
        "url": f"https://api.github.com/repos/{REPO}/issues/{a['child_issue']}",
        "body": child_issue_body(a), "labels": [],
    }


def receipt(a, index=0, outcome="PASS"):
    unit=a["units"][index]
    return make_receipt(
        a, unit_id=unit["id"], input_sha256=unit["input_sha256"],
        outcome=outcome, detail={"evidence":[index,a["agent_id"]]},
        source_run_id=5000+a["child_issue"]*10+index,
    )


def comment(r, cid):
    return {
        "id": cid, "body": receipt_comment_body(r),
        "user":{"login":AUTHOR},
    }


def attest(r):
    return {
        "receipt_id":r["receipt_id"], "source_run_id":r["source_run_id"],
        "source_head_sha":r["source_head_sha"],
        "detail_sha256":r["detail_sha256"],
        "outcome":r["outcome"], "verified":True,
    }



class GithubRead:
    def __init__(self, assignments, *, mutate_after_first_page=False):
        self.issues = {a["child_issue"]: issue(a) for a in assignments}
        self.comments = {a["child_issue"]: [] for a in assignments}
        self.calls = []
        self.mutate_after_first_page = mutate_after_first_page

    def get(self, path, *, query=None):
        self.calls.append((path, query))
        parts = path.split("/")
        if len(parts) == 3 and parts[1] == "issues":
            return copy.deepcopy(self.issues[int(parts[2])])
        if len(parts) == 4 and parts[1] == "issues" and parts[3] == "comments":
            number=int(parts[2])
            page=int(query["page"])
            rows=copy.deepcopy(self.comments[number])
            if self.mutate_after_first_page and len([
                x for x in self.calls if x[0] == path
            ]) > 1:
                rows.append({
                    "id": 999998, "body": "appeared after snapshot",
                    "user": {"login": AUTHOR},
                    "created_at": "2026-11-09T00:00:00Z",
                    "updated_at": "2026-11-09T00:00:00Z",
                })
            return rows[(page-1)*100:page*100]
        raise AssertionError("unapproved read " + path)


def live_comment(r, cid):
    result=comment(r,cid)
    result["created_at"]="2026-11-09T00:00:00Z"
    result["updated_at"]=result["created_at"]
    return result


class LiveChildInventoryTests(unittest.TestCase):
    def test_parent_reads_actual_separate_issues_before_ready(self):
        agents=setup_agents(3,1)
        github=GithubRead(agents)
        for i,a in enumerate(agents):
            github.comments[a["child_issue"]]=[live_comment(receipt(a),i+1)]
        summary=reduce_verified_parent_children(
            github,registry=agents,trusted_comment_authors=frozenset({AUTHOR}),
            live_gate_states={"independent-evidence":"PASS"},
            verify_source=attest,
        )
        self.assertEqual(summary["status"],"READY_FOR_PARENT_REVIEW")
        self.assertEqual(len(summary["children"]),3)
        self.assertFalse(summary["merge_authorized"])
        self.assertIsNone(summary["parent_mutation"])
        self.assertEqual(len(github.calls),9)  # 3 GETs per Child

    def test_full_five_pages_and_short_last_page(self):
        a=setup_agents(1,1)[0]
        github=GithubRead([a])
        github.comments[a["child_issue"]]=[
            {"id":i+1,"body":"unrelated discussion","user":{"login":AUTHOR},
             "created_at":"2026-11-09T00:00:00Z",
             "updated_at":"2026-11-09T00:00:00Z"}
            for i in range(401)
        ]
        result=read_stable_child_comments(github,child_issue=a["child_issue"])
        self.assertEqual(len(result),401)
        self.assertEqual(len(github.calls),10)

    def test_concurrent_mutation_during_inventory_blocks(self):
        a=setup_agents(1,1)[0]
        github=GithubRead([a],mutate_after_first_page=True)
        with self.assertRaisesRegex(AgentIssueError,"changed during inventory"):
            read_stable_child_comments(github,child_issue=a["child_issue"])

    def test_edited_receipt_is_not_accepted_as_immutable(self):
        a=setup_agents(1,1)[0]
        github=GithubRead([a])
        value=live_comment(receipt(a),1)
        value["updated_at"]="2026-11-09T00:00:01Z"
        github.comments[a["child_issue"]]=[value]
        with self.assertRaisesRegex(AgentIssueError,"edited or untraceable"):
            read_stable_child_comments(github,child_issue=a["child_issue"])

    def test_missing_child_issue_and_forged_issue_identity_fail_closed(self):
        a=setup_agents(1,1)[0]
        github=GithubRead([a])
        github.issues[a["child_issue"]]["number"]=300
        with self.assertRaisesRegex(AgentIssueError,"identity mismatch"):
            reduce_verified_parent_children(
                github,registry=[a],
                trusted_comment_authors=frozenset({AUTHOR}),
                live_gate_states={"independent-evidence":"PASS"},
                verify_source=attest,
            )

    def test_one_child_blocks_unverified_finalization(self):
        agents=setup_agents(2,1)
        github=GithubRead(agents)
        github.comments[agents[0]["child_issue"]]=[
            live_comment(receipt(agents[0]),1)
        ]
        github.comments[agents[1]["child_issue"]]=[
            live_comment(receipt(agents[1],outcome="FAIL"),2)
        ]
        summary=reduce_verified_parent_children(
            github,registry=agents,trusted_comment_authors=frozenset({AUTHOR}),
            live_gate_states={"independent-evidence":"PASS"},
            verify_source=attest,
        )
        self.assertEqual(summary["status"],"BLOCKED")
        self.assertFalse(summary["merge_authorized"])
        self.assertIsNone(summary["parent_mutation"])


if __name__=="__main__":
    unittest.main()
