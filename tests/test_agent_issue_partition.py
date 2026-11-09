"""Crash/replay qualification of Agent-specific Child Issue receipt isolation.

Synthetic GitHub Issue records model append-only POST. No actual Issue #44
or production Work Cookie is edited by these tests.
"""
from __future__ import annotations

import copy
import hashlib
import unittest
from concurrent.futures import ThreadPoolExecutor

from chatgpt_operation.controller.agent_issue_partition import (
    AgentIssueError, child_issue_body, make_assignment, make_receipt,
    receipt_comment_body, reduce_child_progress, reduce_parent_children,
    validate_child_ownership, validate_parent_registry,
)
from chatgpt_operation.controller.agent_issue_append import (
    plan_child_append, reconcile_child_append_ack,
)

REPO = "HyungseonSong-plasma/chatgpt-operation"
AUTHOR = "github-actions[bot]"


def sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def setup_agents(n=3, units_each=2):
    assignments=[]
    for i in range(n):
        units = [
            {"id": f"scan-{j}", "input_sha256": sha(f"input/{i}/{j}"),
             "requires": [] if j == 0 else [j - 1],
             "gates": ["independent-evidence"]}
            for j in range(units_each)
        ]
        assignments.append(make_assignment(
            repository=REPO, parent_issue=44, child_issue=1000+i,
            agent_id=f"agent-{i:02}", work_id="issue:44",
            plan_sha256=sha("approved-plan"), policy_sha256=sha("approved-policy"),
            source_head_sha="a"*40, units=units,
        ))
    return assignments


def issue(assignment):
    return {
        "number": assignment["child_issue"],
        "state": "open",
        "url": f"https://api.github.com/repos/{REPO}/issues/{assignment['child_issue']}",
        "body": child_issue_body(assignment),
        "labels": [],
    }


def receipt(assignment, index=0, outcome="PASS", detail=None):
    unit=assignment["units"][index]
    return make_receipt(
        assignment, unit_id=unit["id"],
        input_sha256=unit["input_sha256"],
        outcome=outcome,
        detail={"evidence": [index, assignment["agent_id"]]}
            if detail is None else detail,
        source_run_id=5000 + assignment["child_issue"]*10 + index,
    )


def comment(r, cid):
    return {
        "id": cid,
        "body": receipt_comment_body(r),
        "user": {"login": AUTHOR},
    }


def attest(r):
    # Only in tests: represents independent GitHub run/artifact verification.
    return {
        "receipt_id": r["receipt_id"],
        "source_run_id": r["source_run_id"],
        "source_head_sha": r["source_head_sha"],
        "detail_sha256": r["detail_sha256"],
        "outcome": r["outcome"], "verified": True,
    }


def reduce(assignment, registry, comments, *, verifier=attest, gates=None):
    return reduce_child_progress(
        issue(assignment), comments, assignment,
        parent_registry=registry, trusted_comment_authors=frozenset({AUTHOR}),
        live_gate_states={"independent-evidence": "PASS"} if gates is None else gates,
        verify_source=verifier,
    )


class AgentIssuePartitionTests(unittest.TestCase):
    def test_agent_ownership_is_unique_and_parent_registry_is_authoritative(self):
        agents=setup_agents(3)
        self.assertEqual(validate_parent_registry(agents),agents)
        for a in agents:
            validate_child_ownership(issue(a),a,parent_registry=agents)
        with self.assertRaisesRegex(AgentIssueError,"same Child"):
            validate_parent_registry(agents+[make_assignment(
                repository=REPO,parent_issue=44,child_issue=agents[0]["child_issue"],
                agent_id="intruder",work_id="issue:44",
                plan_sha256=sha("approved-plan"),policy_sha256=sha("approved-policy"),
                source_head_sha="a"*40,units=agents[0]["units"],
            )])
        with self.assertRaisesRegex(AgentIssueError,"duplicate active agent"):
            validate_parent_registry(agents+[make_assignment(
                repository=REPO,parent_issue=44,child_issue=999,
                agent_id=agents[0]["agent_id"],work_id="issue:44",
                plan_sha256=sha("approved-plan"),policy_sha256=sha("approved-policy"),
                source_head_sha="a"*40,units=agents[0]["units"],
            )])

    def test_cross_agent_issue_and_tampered_body_cannot_be_used(self):
        agents=setup_agents()
        other=copy.deepcopy(issue(agents[0]))
        other["number"]=agents[1]["child_issue"]
        with self.assertRaisesRegex(AgentIssueError,"live Child Issue"):
            validate_child_ownership(other,agents[0],parent_registry=agents)
        modified=issue(agents[0])
        modified["body"]=modified["body"].replace("agent-00","agent-01")
        with self.assertRaises(AgentIssueError):
            validate_child_ownership(modified,agents[0],parent_registry=agents)
        admitted=issue(agents[0])
        admitted["labels"]=[{"name":"samuel"}]
        with self.assertRaisesRegex(AgentIssueError,"must not enter"):
            validate_child_ownership(admitted,agents[0],parent_registry=agents)
        with self.assertRaisesRegex(AgentIssueError,"absent from"):
            validate_child_ownership(issue(agents[0]),agents[0],parent_registry=agents[1:])

    def test_each_agent_receives_own_child_and_parent_only_reduces_refs(self):
        agents=setup_agents(3)
        reports=[]
        for assignment in agents:
            r0,r1=receipt(assignment,0),receipt(assignment,1)
            report=reduce(assignment,agents,[comment(r0,11),comment(r1,12)])
            self.assertEqual(report["status"],"COMPLETE")
            self.assertEqual(report["completed_units"],2)
            self.assertIsNone(report["parent_mutation"])
            self.assertFalse(report["merge_authorized"])
            self.assertTrue(all(x["child_issue"]==assignment["child_issue"]
                for x in report["verified_refs"]))
            reports.append(report)
        parent=reduce_parent_children(reports,registry=agents)
        self.assertEqual(parent["status"],"READY_FOR_PARENT_REVIEW")
        self.assertIsNone(parent["parent_mutation"])
        self.assertFalse(parent["merge_authorized"])

    def test_twenty_concurrent_agent_producers_are_physically_partitioned(self):
        agents=setup_agents(20,1)
        with ThreadPoolExecutor(max_workers=10) as pool:
            results=list(pool.map(
                lambda agent: (agent, receipt(agent)),
                agents,
            ))
        self.assertEqual(len({a["child_issue"] for a,_ in results}),20)
        reports=[]
        for index,(a,r) in enumerate(results):
            plan=plan_child_append(
                issue(a),[],a,r,
                parent_registry=agents,trusted_authors=frozenset({AUTHOR}),
            )
            self.assertEqual(plan["path"],f"/issues/{a['child_issue']}/comments")
            self.assertEqual(plan["method"],"POST")
            confirmed=reconcile_child_append_ack(
                [comment(r,100+index)],receipt=r,trusted_authors=frozenset({AUTHOR}),
            )
            self.assertEqual(confirmed["logical_receipts"],1)
            reports.append(reduce(a,agents,[comment(r,100+index)]))
        self.assertEqual(reduce_parent_children(reports,registry=agents)["status"],
            "READY_FOR_PARENT_REVIEW")
        self.assertEqual(sum(x["completed_units"] for x in reports),20)
        print("AGENT_CHILD_PARTITION=PASS agents=20 separate_issues=20 "
              "verified_units=20 shared_comment_patch=0 parent_mutations=0",
              flush=True)

    def test_lost_post_ack_restart_is_idempotent_without_patch(self):
        agents=setup_agents(1,1)
        a=agents[0]
        r=receipt(a)
        planned=plan_child_append(issue(a),[],a,r,parent_registry=agents,
            trusted_authors=frozenset({AUTHOR}))
        self.assertEqual(planned["status"],"APPEND_PROPOSAL")
        self.assertEqual(planned["method"],"POST")
        # POST happened remotely; HTTP acknowledgement was dropped.
        durable=[comment(r,200)]
        found=reconcile_child_append_ack(
            durable,receipt=r,trusted_authors=frozenset({AUTHOR}))
        self.assertEqual(found["status"],"COMMITTED_APPEND")
        restart=plan_child_append(issue(a),durable,a,r,parent_registry=agents,
            trusted_authors=frozenset({AUTHOR}))
        self.assertEqual(restart["status"],"ALREADY_PRESENT")
        self.assertIsNone(restart["method"])
        self.assertEqual(reduce(a,agents,durable)["completed_units"],1)

    def test_duplicate_post_ack_is_one_logical_receipt(self):
        agents=setup_agents(1,1)
        a=agents[0]
        r=receipt(a)
        durable=[comment(r,200),comment(r,201),comment(r,202)]
        result=reconcile_child_append_ack(
            durable,receipt=r,trusted_authors=frozenset({AUTHOR}))
        self.assertEqual(result["status"],"COMMITTED_APPEND")
        self.assertEqual(result["comment_ids"],[200,201,202])
        self.assertEqual(result["logical_receipts"],1)
        self.assertEqual(reduce(a,agents,durable)["completed_units"],1)

    def test_same_unit_conflict_blocks_instead_of_overwriting(self):
        agents=setup_agents(1,1)
        a=agents[0]
        r0=receipt(a)
        r1=receipt(a,detail={"different":"result"})
        with self.assertRaisesRegex(AgentIssueError,"conflicting evidence"):
            plan_child_append(issue(a),[comment(r0,200)],a,r1,
                parent_registry=agents,trusted_authors=frozenset({AUTHOR}))
        with self.assertRaisesRegex(AgentIssueError,"contradictory receipts"):
            reduce(a,agents,[comment(r0,200),comment(r1,201)])

    def test_foreign_receipt_is_not_accepted_into_child(self):
        agents=setup_agents(2,1)
        with self.assertRaisesRegex(AgentIssueError,"another Agent"):
            plan_child_append(issue(agents[0]),[],agents[0],receipt(agents[1]),
                parent_registry=agents,trusted_authors=frozenset({AUTHOR}))
        with self.assertRaisesRegex(AgentIssueError,"crosses agent"):
            reduce(agents[0],agents,[comment(receipt(agents[1]),199)])

    def test_untrusted_author_and_unverified_execution_are_refused(self):
        agents=setup_agents(1,1)
        a=agents[0]
        r=receipt(a)
        bad=comment(r,200)
        bad["user"]["login"]="external"
        with self.assertRaisesRegex(AgentIssueError,"unauthorized"):
            reduce(a,agents,[bad])
        with self.assertRaisesRegex(AgentIssueError,"attestation mismatch"):
            reduce(a,agents,[comment(r,200)],verifier=lambda _: {
                **attest(r),"source_run_id":9999,
            })
        with self.assertRaisesRegex(AgentIssueError,"independent"):
            reduce(a,agents,[comment(r,200)],verifier=None)

    def test_gate_failure_and_prerequisites_fail_closed(self):
        agents=setup_agents(1,2)
        a=agents[0]
        r0,r1=receipt(a,0),receipt(a,1)
        with self.assertRaisesRegex(AgentIssueError,"dependencies/gates"):
            reduce(a,agents,[comment(r0,200)],gates={"independent-evidence":"UNKNOWN"})
        with self.assertRaisesRegex(AgentIssueError,"dependencies/gates"):
            reduce(a,agents,[comment(r1,201)])
        self.assertEqual(reduce(a,agents,[comment(r0,200)])["status"],"IN_PROGRESS")

    def test_failure_is_recorded_but_never_authorizes_merge(self):
        agents=setup_agents(1,1)
        r=receipt(agents[0],outcome="FAIL",detail={"error":"read-only audit failed"})
        result=reduce(agents[0],agents,[comment(r,200)])
        self.assertEqual(result["status"],"BLOCKED")
        self.assertEqual(result["completed_units"],0)
        self.assertEqual(len(result["failed_receipts"]),1)
        self.assertEqual(reduce_parent_children([result],registry=agents)["status"],"BLOCKED")

    def test_parent_requires_complete_exact_child_inventory(self):
        agents=setup_agents(2,1)
        report=reduce(agents[0],agents,[comment(receipt(agents[0]),100)])
        with self.assertRaisesRegex(AgentIssueError,"incomplete"):
            reduce_parent_children([report],registry=agents)
        with self.assertRaisesRegex(AgentIssueError,"duplicate Child"):
            reduce_parent_children([report,report],registry=agents)
        forged=copy.deepcopy(report)
        forged["child_issue"]=agents[1]["child_issue"]
        with self.assertRaisesRegex(AgentIssueError,"untrusted or missing"):
            reduce_parent_children([report,forged],registry=agents)

    def test_unacknowledged_append_is_unknown_not_committed(self):
        a=setup_agents(1,1)[0]
        result=reconcile_child_append_ack([],
            receipt=receipt(a),trusted_authors=frozenset({AUTHOR}))
        self.assertEqual(result["status"],"UNKNOWN_WRITE_RESULT")
        self.assertEqual(result["comment_ids"],[])

    def test_append_only_wire_contract_has_no_shared_comment_patch(self):
        from pathlib import Path
        source=Path(
            "src/chatgpt_operation/controller/agent_issue_append.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn('transport.request("PATCH"',source)
        self.assertIn('"method": "POST"',source)
        self.assertIn('"parent_mutation": None',
                      Path("src/chatgpt_operation/controller/agent_issue_partition.py")
                      .read_text(encoding="utf-8"))


if __name__=="__main__":
    unittest.main()
