"""Qualification of the existing Bootstrap as exclusive progress-state writer.

The worker requests are simulated authenticated, complete GitHub Actions run
artifacts. No production Issue or workflow is mutated from this test.
"""
from __future__ import annotations

import copy
import hashlib
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from chatgpt_operation.controller.durable_state import (
    encode_state, load_state_comment,
)
from chatgpt_operation.controller.progress_resume import (
    attach_checkpoint, create_checkpoint, detail_digest,
)
from chatgpt_operation.controller.research import ResearchState
from chatgpt_operation.controller.single_writer_pilot import (
    SingleWriterError, create_intent, decode_inbox_comment,
    encode_inbox_comment, plan_progress_write, read_inbox, validate_intent,
)
from chatgpt_operation.controller.state_persistence import (
    persist_state_write,
)


def sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def seed(n=20):
    ids = [f"scan-{i:02}" for i in range(n)]
    units = [
        {"id": name, "input_sha256": sha(name), "requires": [],
         "gates": ["verified_evidence"]}
        for name in ids
    ]
    state = attach_checkpoint(
        ResearchState("issue:qualification", "read-only scoped audit"),
        create_checkpoint(
            work_id="issue:qualification",
            plan_sha256=sha("approved-plan"),
            policy_sha256=sha("approved-policy"),
            units=units,
        ),
    )
    return state, ids


def make_worker_request(state, unit_id, number, *, result=None):
    cp = state.progress_checkpoint
    detail = result if result is not None else {
        "kind": "read-only-test-evidence",
        "unit": unit_id,
        "source_revision": "a" * 40,
        "path": f"docs/{unit_id}.md",
        "findings": [{"line": number + 1, "match": "../README.md"}],
    }
    source = {
        "repository": "HyungseonSong-plasma/chatgpt-operation",
        "workflow": "samuel-evidence-acquisition.yml",
        "run_id": 10000 + number,
        "head_sha": "a" * 40,
        "artifact_sha256": sha("artifact:" + unit_id),
    }
    return create_intent(
        work_id=state.research_id,
        base_revision=state.revision,
        plan_sha256=cp["plan_sha256"],
        policy_sha256=cp["policy_sha256"],
        unit_id=unit_id,
        input_sha256=sha(unit_id),
        outcome="PASS",
        detail=detail,
        source=source,
    )


def independently_verified(intent):
    # The test double models an already authenticated GitHub readback.
    # In production this must be fetched from the actual run and artifact.
    return {
        **intent["source"],
        "conclusion": "success",
        "work_id": intent["work_id"],
        "unit_id": intent["unit_id"],
        "input_sha256": intent["input_sha256"],
        "outcome": intent["outcome"],
        "detail_sha256": intent["detail_sha256"],
    }


class IssueTransport:
    """Issue-comment API simulator with crash-after-write failure injection."""

    def __init__(self, comments):
        self.comments = copy.deepcopy(comments)
        self.calls = []
        self.lost_ack = False

    def get(self, path, *, query=None):
        self.calls.append(("GET", path))
        return copy.deepcopy(self.comments)

    def request(self, method, path, *, payload=None):
        self.calls.append((method, path))
        if method != "PATCH":
            raise AssertionError("progress pilot must not create state comments")
        comment_id = int(path.rsplit("/", 1)[-1])
        target = next(c for c in self.comments if c["id"] == comment_id)
        target["body"] = payload["body"]
        if self.lost_ack:
            self.lost_ack = False
            raise TimeoutError("accepted PATCH, reply was lost")
        return 200, copy.deepcopy(target)


def comment_state(state):
    return {
        "id": 44,
        "user": {"login": "github-actions[bot]"},
        "body": encode_state(state),
    }


def submit_inbox(transport, items):
    for index, intent in enumerate(items):
        transport.comments.append({
            "id": 3000 + index,
            "user": {"login": "github-actions[bot]"},
            "body": encode_inbox_comment(intent),
        })


def plan(transport, intent, *, verifier=None, gates=None):
    return plan_progress_write(
        transport.get("/issues/44/comments"),
        intent,
        verify_source=(lambda _source: independently_verified(intent))
        if verifier is None else verifier,
        allowed_repository="HyungseonSong-plasma/chatgpt-operation",
        allowed_workflows=frozenset({"samuel-evidence-acquisition.yml"}),
        live_gate_states={"verified_evidence": "PASS"} if gates is None else gates,
    )


class SingleWriterPilotTests(unittest.TestCase):
    def test_twenty_parallel_workers_one_serial_writer_and_resume_after_crash(self):
        state, names = seed(20)
        transport = IssueTransport([comment_state(state)])
        with ThreadPoolExecutor(max_workers=10) as pool:
            intents = list(pool.map(
                lambda numbered: make_worker_request(state, numbered[1], numbered[0]),
                enumerate(names),
            ))
        self.assertEqual(len({x["request_id"] for x in intents}), 20)
        submit_inbox(transport, intents)

        # Bootstrap's *single* writer serially commits one verified unit at
        # a time. Producers can be parallel but have no state-write ability.
        first_inbox = read_inbox(
            transport.get("/issues/44/comments"),
            trusted_authors=frozenset({"github-actions[bot]"}),
        )
        self.assertEqual(len(first_inbox), 20)
        for request in first_inbox[:10]:
            proposal = plan(transport, request)
            self.assertEqual(proposal["status"], "WRITE_PROPOSAL")
            persist_state_write(
                transport, issue_number=44, request=proposal["state_write"],
            )

        # Crash: throw away writer memory; the original append-only inbox
        # and the canonical state remain in the Issue-shaped transport.
        restarted = IssueTransport(transport.comments)
        before = load_state_comment(restarted.get("/issues/44/comments"))
        self.assertEqual(len(before.progress_checkpoint["receipts"]), 10)
        processed_after_restart = []
        for request in read_inbox(
            restarted.get("/issues/44/comments"),
            trusted_authors=frozenset({"github-actions[bot]"}),
        ):
            proposal = plan(restarted, request)
            if proposal["status"] == "ALREADY_APPLIED":
                continue
            self.assertEqual(proposal["status"], "WRITE_PROPOSAL")
            processed_after_restart.append(request["unit_id"])
            persist_state_write(
                restarted, issue_number=44, request=proposal["state_write"],
            )
        self.assertEqual(processed_after_restart, names[10:])
        after = load_state_comment(restarted.get("/issues/44/comments"))
        self.assertEqual(len(after.progress_checkpoint["receipts"]), 20)
        self.assertEqual(after.revision - before.revision, 10)
        self.assertEqual(
            after.progress_checkpoint["receipts"]["0"],
            before.progress_checkpoint["receipts"]["0"],
        )
        self.assertEqual(
            [p for p in read_inbox(
                restarted.get("/issues/44/comments"),
                trusted_authors=frozenset({"github-actions[bot]"}),
            ) if plan(restarted, p)["status"] != "ALREADY_APPLIED"],
            [],
        )
        self.assertEqual(len(restarted.comments), 21)
        print(
            "SINGLE_WRITER=PASS parallel_producers=20 "
            "committed_before_crash=10 resumed=10 final_receipts=20 "
            "duplicates=0 state_comments=1",
            flush=True,
        )

    def test_patch_ack_lost_is_reconciled_without_second_write(self):
        state, names = seed(1)
        transport = IssueTransport([comment_state(state)])
        intent = make_worker_request(state, names[0], 0)
        submit_inbox(transport, [intent])
        proposal = plan(transport, intent)
        transport.lost_ack = True
        with self.assertRaisesRegex(TimeoutError, "reply was lost"):
            persist_state_write(
                transport, issue_number=44, request=proposal["state_write"],
            )
        # Fresh writer must not replay a successful write just because the
        # transport did not acknowledge it.
        second = IssueTransport(transport.comments)
        recovered = plan(second, intent)
        self.assertEqual(recovered["status"], "ALREADY_APPLIED")
        self.assertIsNone(recovered["state_write"])
        self.assertNotIn("PATCH", [call[0] for call in second.calls])

    def test_tampered_source_or_bad_gate_must_never_persist(self):
        state, ids = seed(1)
        transport = IssueTransport([comment_state(state)])
        intent = make_worker_request(state, ids[0], 0)
        bad = dict(intent)
        bad["detail"] = {"forged": True}
        with self.assertRaisesRegex(SingleWriterError, "detail digest"):
            plan(transport, bad)
        with self.assertRaisesRegex(SingleWriterError, "source evidence"):
            plan(transport, intent, verifier=lambda _: {
                **independently_verified(intent), "detail_sha256": sha("forged"),
            })
        with self.assertRaisesRegex(SingleWriterError, "source run is not"):
            plan(transport, intent, verifier=lambda _: {
                **independently_verified(intent), "conclusion": "failure",
            })
        with self.assertRaisesRegex(SingleWriterError, "required gate"):
            plan(transport, intent, gates={"verified_evidence": "UNKNOWN"})
        self.assertNotIn("PATCH", [call[0] for call in transport.calls])

    def test_stale_worker_proposal_is_rebased_only_when_scope_is_stable(self):
        state, ids = seed(2)
        transport = IssueTransport([comment_state(state)])
        a = make_worker_request(state, ids[0], 0)
        b = make_worker_request(state, ids[1], 1)
        persist_state_write(
            transport, issue_number=44, request=plan(transport, a)["state_write"],
        )
        self.assertEqual(plan(transport, b)["status"], "WRITE_PROPOSAL")
        tampered = copy.deepcopy(transport.comments)
        current = load_state_comment(tampered)
        current.progress_checkpoint["policy_sha256"] = sha("changed-policy")
        tampered[0]["body"] = encode_state(current)
        blocked = IssueTransport(tampered)
        with self.assertRaisesRegex(SingleWriterError, "plan or policy advanced"):
            plan(blocked, b)

    def test_same_unit_conflict_is_not_automatically_merged(self):
        state, ids = seed(1)
        transport = IssueTransport([comment_state(state)])
        a = make_worker_request(state, ids[0], 0)
        b = make_worker_request(
            state, ids[0], 0, result={"different": "valid but conflicting"},
        )
        persist_state_write(
            transport, issue_number=44, request=plan(transport, a)["state_write"],
        )
        with self.assertRaisesRegex(SingleWriterError, "conflicting replay"):
            plan(transport, b)
        self.assertEqual(len(load_state_comment(
            transport.get("/issues/44/comments")
        ).progress_checkpoint["receipts"]), 1)

    def test_inbox_requires_trusted_author_and_canonical_identity(self):
        state, ids = seed(1)
        intent = make_worker_request(state, ids[0], 0)
        body = encode_inbox_comment(intent)
        self.assertEqual(decode_inbox_comment(body), intent)
        duplicated = read_inbox([
            {"id": 4, "user": {"login": "github-actions[bot]"}, "body": body},
            {"id": 5, "user": {"login": "github-actions[bot]"}, "body": body},
        ], trusted_authors=frozenset({"github-actions[bot]"}))
        self.assertEqual(len(duplicated), 1)
        with self.assertRaisesRegex(SingleWriterError, "untrusted inbox"):
            read_inbox([
                {"id": 6, "user": {"login": "external"}, "body": body},
            ], trusted_authors=frozenset({"github-actions[bot]"}))
        with self.assertRaisesRegex(SingleWriterError, "inbox marker"):
            decode_inbox_comment(body.replace("state-write-intent-v1:", "state-write-intent-v2:"))
        changed = copy.deepcopy(intent)
        changed["source"]["run_id"] += 1
        with self.assertRaisesRegex(SingleWriterError, "request id"):
            validate_intent(changed)

    def test_source_execution_and_unverified_queue_are_never_write_authority(self):
        state, ids = seed(1)
        state.action_queue["other"] = {"status": "dispatch_intent"}
        transport = IssueTransport([comment_state(state)])
        intent = make_worker_request(state, ids[0], 0)
        with self.assertRaisesRegex(SingleWriterError, "active execution"):
            plan(transport, intent)
        self.assertNotIn("PATCH", [x[0] for x in transport.calls])

    def test_bootstrap_only_has_durable_state_write_cli_calls(self):
        paths = sorted(Path(".github/workflows").glob("*.yml"))
        write_calls = []
        for path in paths:
            content = path.read_text(encoding="utf-8")
            if "controller persist-state" in content:
                write_calls.append(path.name)
        self.assertEqual(write_calls, ["samuel-bootstrap.yml"])
        workflow = Path(".github/workflows/samuel-bootstrap.yml").read_text(encoding="utf-8")
        self.assertIn("group: samuel-bootstrap", workflow)
        self.assertIn("cancel-in-progress: false", workflow)


if __name__ == "__main__":
    unittest.main()
