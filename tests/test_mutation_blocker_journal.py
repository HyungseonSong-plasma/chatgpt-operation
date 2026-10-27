"""Fake-transport and regression tests for durable blocker journal/prewrite gate."""
from __future__ import annotations

import json
import unittest

from chatgpt_operation.repository.blocker_triage import (
    BlockerObservation, BlockerSource, logical_intent_id,
)
from chatgpt_operation.repository.blocker_resolution import ClearanceEvidence, ClearanceKind
from chatgpt_operation.repository.blocker_journal import (
    GitHubIssueBlockerJournal, JournalError, MARKER,
)
from chatgpt_operation.repository.blocker_gate import CommonPreWriteGate, BlockerGateError

HEAD = "f" * 40
OTHER_HEAD = "d" * 40
INTENT = logical_intent_id(
    repository="HyungseonSong-plasma/chatgpt-operation", branch="samuel/236",
    work_id="owner-issued-236", paths=("docs/policy.md",),
)


class IssueAPI:
    def __init__(self):
        self.comments = []
        self.failure = False
        self.next_writer = "samuel-bot"
        self.writes = 0

    def get(self, path, *, query=None):
        if self.failure:
            raise OSError("read unavailable")
        if path != "/issues/236/comments":
            raise AssertionError(path)
        page = int(query["page"])
        offset = (page - 1) * 100
        return [dict(x) for x in self.comments[offset:offset + 100]]

    def request(self, method, path, *, payload=None):
        if method != "POST" or path != "/issues/236/comments":
            raise AssertionError((method, path))
        self.writes += 1
        item = {"id": len(self.comments) + 1,
                "body": payload["body"], "user": {"login": self.next_writer}}
        self.comments.append(item)
        return dict(item)


def blocker(*, source=BlockerSource.TOOL_SAFETY, ref="deny-1"):
    return BlockerObservation(source, INTENT, "github-connector", ref)


def proof(kind=ClearanceKind.UPSTREAM_SAFETY_CLEARED, *,
          head=HEAD, ref="clear-2"):
    return ClearanceEvidence(INTENT, "deny-1", kind, head, ref)


class MutationBlockerJournalTests(unittest.TestCase):
    def setUp(self):
        self.api = IssueAPI()
        self.journal = GitHubIssueBlockerJournal(
            self.api, issue_number=236, trusted_actor="samuel-bot")

    def gate(self, *, head=HEAD, tech=None, authority=None):
        return CommonPreWriteGate(
            journal=self.journal, trusted_head_reader=lambda: head,
            technical_verifier=tech or (lambda _: False),
            authority_verifier=authority or (lambda _: False),
        )

    def test_empty_complete_history_does_not_grant_mutation_authority(self):
        r = self.gate().evaluate(logical_intent_id=INTENT, expected_head_sha=HEAD)
        self.assertTrue(r.no_active_blocker)
        self.assertFalse(r.write_authorized)
        self.assertEqual(r.checked_events, 0)

    def test_persistent_issue_comment_read_after_new_journal_instance(self):
        after = self.journal.record_blocker(blocker())
        self.assertEqual(len(after.events), 1)
        self.assertEqual(self.api.writes, 1)
        recovered = GitHubIssueBlockerJournal(
            self.api, issue_number=236, trusted_actor="samuel-bot").read()
        self.assertEqual(recovered.tip, after.tip)
        self.assertEqual(recovered.events, after.events)
        with self.assertRaisesRegex(BlockerGateError, "ACTIVE_BLOCKER"):
            self.gate().require_clear(logical_intent_id=INTENT, expected_head_sha=HEAD)

    def test_safety_denial_never_cleared_by_technical_attestation(self):
        self.journal.record_blocker(blocker())
        self.journal.record_clearance(proof())
        with self.assertRaisesRegex(BlockerGateError, "ACTIVE_BLOCKER"):
            self.gate(tech=lambda _: True).require_clear(
                logical_intent_id=INTENT, expected_head_sha=HEAD)
        approved = self.gate(authority=lambda _: True).require_clear(
            logical_intent_id=INTENT, expected_head_sha=HEAD)
        self.assertTrue(approved.no_active_blocker)
        self.assertFalse(approved.write_authorized)

    def test_technical_ci_clearance_auto_recovers_but_requires_current_sha(self):
        b = blocker(source=BlockerSource.CI)
        self.journal.record_blocker(b)
        self.journal.record_clearance(proof(ClearanceKind.EXACT_HEAD_CI_PASS))
        self.assertTrue(self.gate(tech=lambda _: True).evaluate(
            logical_intent_id=INTENT, expected_head_sha=HEAD).no_active_blocker)
        self.assertFalse(self.gate(head=OTHER_HEAD, tech=lambda _: True).evaluate(
            logical_intent_id=INTENT, expected_head_sha=OTHER_HEAD).no_active_blocker)

    def test_access_denial_requires_exact_permission_recovery_evidence(self):
        b = BlockerObservation(BlockerSource.GITHUB_HTTP, INTENT, "connector", "deny-1", 403)
        self.journal.record_blocker(b)
        self.journal.record_clearance(proof(ClearanceKind.TARGET_ACCESS_RESTORED))
        self.assertFalse(self.gate().evaluate(logical_intent_id=INTENT, expected_head_sha=HEAD).no_active_blocker)
        self.assertTrue(self.gate(tech=lambda _: True).evaluate(
            logical_intent_id=INTENT, expected_head_sha=HEAD).no_active_blocker)

    def test_a_second_uncleared_blocker_still_blocks(self):
        self.journal.record_blocker(blocker(ref="deny-1"))
        self.journal.record_clearance(proof())
        self.journal.record_blocker(blocker(ref="deny-3"))
        self.assertFalse(self.gate(authority=lambda _: True).evaluate(
            logical_intent_id=INTENT, expected_head_sha=HEAD).no_active_blocker)

    def test_duplicate_append_is_idempotent_and_new_evidence_is_not(self):
        self.journal.record_blocker(blocker())
        same = self.journal.record_blocker(blocker())
        self.assertEqual(len(same.events), 1)
        self.assertEqual(self.api.writes, 1)
        self.journal.record_blocker(blocker(ref="new-failure"))
        self.assertEqual(len(self.journal.read().events), 2)

    def test_invalid_or_missing_clearance_parent_rejected(self):
        with self.assertRaises(JournalError):
            self.journal.record_clearance(proof())
        self.assertEqual(self.api.writes, 0)

    def test_unauthorized_journal_writer_fails_closed(self):
        self.api.next_writer = "unexpected"
        with self.assertRaises(JournalError):
            self.journal.record_blocker(blocker())
        with self.assertRaises(JournalError):
            self.journal.read()
        with self.assertRaises(BlockerGateError):
            self.gate().require_clear(logical_intent_id=INTENT, expected_head_sha=HEAD)

    def test_corrupt_middle_hash_detected(self):
        self.journal.record_blocker(blocker())
        self.journal.record_blocker(blocker(ref="deny-2"))
        entry = json.loads(self.api.comments[0]["body"][len(MARKER):])
        entry["payload"]["evidence_ref"] = "edited"
        self.api.comments[0]["body"] = MARKER + json.dumps(entry)
        with self.assertRaisesRegex(JournalError, "hash chain"):
            self.journal.read()

    def test_complete_enumeration_failure_blocks_gate(self):
        self.journal.record_blocker(blocker())
        self.api.failure = True
        with self.assertRaises(BlockerGateError):
            self.gate(authority=lambda _: True).require_clear(
                logical_intent_id=INTENT, expected_head_sha=HEAD)

    def test_stale_expected_head_rejected_before_journal_read(self):
        with self.assertRaisesRegex(BlockerGateError, "stale"):
            self.gate(head=HEAD).require_clear(logical_intent_id=INTENT,
                                               expected_head_sha=OTHER_HEAD)

    def test_unrelated_issue_comment_does_not_change_chain(self):
        self.api.comments.append({"id": 1, "body": "normal issue discussion",
                                  "user": {"login": "any"}})
        x = self.journal.record_blocker(blocker())
        self.assertEqual(len(x.events), 1)
        self.assertEqual(x.last_comment_id, 2)

    def test_paginated_unrelated_comments_are_exhaustively_read(self):
        self.api.comments = [{"id": i, "body": "note", "user": {"login": "any"}}
                             for i in range(1, 101)]
        self.journal.record_blocker(blocker())
        self.assertEqual(len(self.journal.read().events), 1)

    def test_changed_work_scope_same_controller_work_id_remains_blocked(self):
        self.journal.record_blocker(blocker())
        new_scope = logical_intent_id(
            repository="HyungseonSong-plasma/chatgpt-operation",
            branch="samuel/236-new-branch", work_id="owner-issued-236",
            paths=("src/renamed.py",))
        self.assertEqual(INTENT, new_scope)
        self.assertFalse(self.gate().evaluate(
            logical_intent_id=new_scope, expected_head_sha=HEAD).no_active_blocker)


if __name__ == "__main__":
    unittest.main()
