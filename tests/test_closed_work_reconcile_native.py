"""Native StateKernel and Admission readback tests; no real GitHub mutation."""
from __future__ import annotations

import copy
import json
import unittest

from chatgpt_operation.controller.closed_work_reconciliation import (
    BRANCH, EXPECTED_REF_SHA, REPO,
)
from chatgpt_operation.controller.closed_work_reconcile_native import (
    NoopReleaseError, reconcile_native,
)
from chatgpt_operation.controller.durable_state import (
    can_rollover_state, encode_state, decode_state,
)
from chatgpt_operation.controller.issue_ingestion import (
    encode_admission_ledger, decode_admission_ledger,
)
from chatgpt_operation.controller.research import ResearchState
from chatgpt_operation.github.actions_runtime import ActionsApiError

SHA = "a" * 40
FINGERPRINT = "5c12a213f3030f9bc4b9e6d8aab108fe5c43d448566ac5a04a8dbb3332227111"


def comment(id, body, author="HyungseonSong-plasma"):
    return {
        "id": id, "body": body,
        "user": {"login": author},
        "created_at": "2026-11-09T00:00:00Z",
        "updated_at": "2026-11-09T00:00:00Z",
    }


class NativeReadbackFake:
    repository = REPO

    def __init__(self):
        state = ResearchState("issue:255", "cleanup verification")
        state.revision = 2
        state.predispatch_failures = {
            FINGERPRINT: {
                "schema_version": 1, "fingerprint": FINGERPRINT,
                "work_id": "issue:255", "status": "escalated",
                "occurrences": 2, "failure_class": "reasoning_validation",
                "target_acceptance_criterion": None,
                "last_error": "OpenAI reasoning provider HTTP request failed",
                "node_attempts": None, "branch_identity": None,
                "capability_exhaustion_proven": False,
            },
        }
        ledger = {
            "issue:255": {"work_id": "issue:255", "status": "reasoning_required"},
            "issue:256": {"work_id": "issue:256", "status": "admitted"},
        }
        self.global_comments = [
            comment(101, encode_state(state)),
            comment(102, encode_admission_ledger(ledger)),
        ]
        self.global_comments[0]["user"]["login"] = "github-actions[bot]"
        self.global_comments[1]["user"]["login"] = "github-actions[bot]"
        self.issues = {
            255: {
                "number": 255, "state": "closed",
                "body": f"Target {BRANCH} exact {EXPECTED_REF_SHA}",
            },
            256: {
                "number": 256, "state": "closed",
                "title": "[Samuel diagnostic A] Read-only reasoning baseline",
            },
        }
        self.comments255 = [
            comment(6735864890,
                    f"NO_MUTATION_NEEDED {BRANCH} {EXPECTED_REF_SHA} 404"),
            comment(8008,
                    "<!-- samuel-closed-work-reconcile-release-v1 -->\n"
                    f"release issue:255 and issue:256; {BRANCH}, {EXPECTED_REF_SHA}, "
                    "NO_MUTATION_NEEDED, preserve escalation"),
        ]
        self.comments256 = [
            comment(
                6745233284,
                "<!-- samuel-256-diagnostic-closure-v1 --> "
                "401 invalid_api_key; model DID NOT SUCCEED",
            ),
        ]
        self.branch_present = False
        self.open_samuel = []
        self.head = SHA
        self.patches = []

    def get(self, path, *, query=None):
        if path == "/branches/main":
            return {"commit": {"sha": self.head}}
        if path == f"/git/ref/heads/{BRANCH}" or path == f"/branches/{BRANCH}":
            if self.branch_present:
                return {"ref": "present"}
            raise ActionsApiError("not found", status=404)
        if path == f"/git/matching-refs/heads/{BRANCH}":
            return [] if not self.branch_present else [{"ref": BRANCH}]
        if path == "/issues/255": return copy.deepcopy(self.issues[255])
        if path == "/issues/256": return copy.deepcopy(self.issues[256])
        if path == "/issues":
            if query is None or query.get("labels") != "samuel":
                raise AssertionError("unexpected global Issue enumeration")
            return copy.deepcopy(self.open_samuel)
        data = {
            "/issues/255/comments": self.comments255,
            "/issues/256/comments": self.comments256,
            "/issues/44/comments": self.global_comments,
        }.get(path)
        if data is None:
            raise AssertionError("unapproved native REST GET " + path)
        if query and query.get("page"):
            page = int(query["page"])
            return copy.deepcopy(data[(page-1)*100:page*100])
        return copy.deepcopy(data)

    def request(self, method, path, *, payload=None):
        if method != "PATCH" or not path.startswith("/issues/comments/"):
            raise AssertionError("unapproved native REST mutation")
        cid = int(path.split("/")[-1])
        for row in self.global_comments:
            if row["id"] == cid:
                row["body"] = payload["body"]
                self.patches.append(cid)
                return 200, copy.deepcopy(row)
        raise AssertionError("PATCH target not the authoritative #44 comment")


class LiveNoopReleaseTests(unittest.TestCase):
    def test_complete_reconciliation_is_idempotent_and_preserves_history(self):
        rest = NativeReadbackFake()
        first = reconcile_native(
            rest, expected_main_sha=SHA, owner_event_comment_id=8008,
        )
        self.assertEqual(first["status"], "PASS")
        self.assertEqual(first["revision"], 3)
        self.assertEqual(rest.patches, [102, 101])
        state = decode_state(rest.global_comments[0]["body"])
        self.assertTrue(can_rollover_state(state))
        self.assertEqual(state.predispatch_failures[FINGERPRINT]["status"], "escalated")
        ledger = decode_admission_ledger(rest.global_comments[1]["body"])
        self.assertEqual(ledger["issue:255"]["status"], "complete")
        self.assertEqual(ledger["issue:256"]["status"], "complete")
        again = reconcile_native(
            rest, expected_main_sha=SHA, owner_event_comment_id=8008,
        )
        self.assertEqual(again["status"], "NO_MUTATION_NEEDED")
        self.assertEqual(rest.patches, [102, 101])

    def test_wrong_owner_event_comment_is_denied(self):
        fake = NativeReadbackFake()
        with self.assertRaises(NoopReleaseError):
            reconcile_native(fake, expected_main_sha=SHA, owner_event_comment_id=9999)
        self.assertEqual(fake.patches, [])

    def test_present_branch_never_allows_mutation(self):
        fake = NativeReadbackFake()
        fake.branch_present = True
        with self.assertRaises(NoopReleaseError):
            reconcile_native(fake, expected_main_sha=SHA, owner_event_comment_id=8008)
        self.assertEqual(fake.patches, [])

    def test_concurrent_main_head_change_blocks(self):
        fake = NativeReadbackFake()
        fake.head = "b" * 40
        with self.assertRaises(NoopReleaseError):
            reconcile_native(fake, expected_main_sha=SHA, owner_event_comment_id=8008)
        self.assertEqual(fake.patches, [])

    def test_active_other_samuel_issue_blocks(self):
        fake = NativeReadbackFake()
        fake.open_samuel = [{"id": 1, "number": 999, "state": "open"}]
        with self.assertRaises(NoopReleaseError):
            reconcile_native(fake, expected_main_sha=SHA, owner_event_comment_id=8008)
        self.assertEqual(fake.patches, [])

    def test_historical_error_change_never_writes(self):
        fake = NativeReadbackFake()
        state = decode_state(fake.global_comments[0]["body"])
        state.predispatch_failures[FINGERPRINT]["status"] = "resolved"
        fake.global_comments[0]["body"] = encode_state(state)
        with self.assertRaises(ValueError):
            reconcile_native(fake, expected_main_sha=SHA, owner_event_comment_id=8008)
        self.assertEqual(fake.patches, [])

    def test_ledger_partial_commit_can_resume_without_second_ledger_patch(self):
        fake = NativeReadbackFake()
        changed = decode_admission_ledger(fake.global_comments[1]["body"])
        changed["issue:255"]["status"] = "complete"
        changed["issue:256"]["status"] = "complete"
        fake.global_comments[1]["body"] = encode_admission_ledger(changed)
        result = reconcile_native(
            fake, expected_main_sha=SHA, owner_event_comment_id=8008,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(fake.patches, [101])


if __name__ == "__main__":
    unittest.main()
