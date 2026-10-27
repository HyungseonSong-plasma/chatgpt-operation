"""Adversarial checkpoint tests: hash chain alone cannot see tail deletion."""
import unittest

from chatgpt_operation.repository.blocker_checkpoint import (
    JournalCheckpoint, require_checkpoint,
)
from chatgpt_operation.repository.blocker_gate import CommonPreWriteGate, BlockerGateError
from chatgpt_operation.repository.blocker_journal import (
    GitHubIssueBlockerJournal, JournalError,
)
from chatgpt_operation.repository.blocker_triage import logical_intent_id

REPO = "HyungseonSong-plasma/chatgpt-operation"
SHA = "a" * 40
INTENT = logical_intent_id(repository=REPO, branch="samuel/test",
                           work_id="trusted-checkpoint-test",
                           paths=("docs/checkpoint.md",))


class IssueTransport:
    def __init__(self):
        self.comments = []

    def get(self, path, *, query=None):
        if path != "/issues/236/comments":
            raise AssertionError(path)
        page = int(query["page"])
        return [dict(item) for item in self.comments[(page - 1) * 100:page * 100]]

    def request(self, method, path, *, payload=None):
        if method != "POST" or path != "/issues/236/comments":
            raise AssertionError((method, path))
        entry = {"id": 1 + len(self.comments), "body": payload["body"],
                 "user": {"login": "trusted-bot"}}
        self.comments.append(entry)
        return entry


class IndependentJournalCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.transport = IssueTransport()
        self.journal = GitHubIssueBlockerJournal(
            self.transport, issue_number=236, trusted_actor="trusted-bot",
        )
        self.journal.register_work(
            logical_intent_id=INTENT, exact_head_sha=SHA,
            evidence_ref="trusted-controller-enrollment",
        )
        self.snapshot = self.journal.read()
        self.anchor = JournalCheckpoint(
            sequence=len(self.snapshot.events), tip=self.snapshot.tip,
            anchor_ref="independent-protected-checkpoint:236",
        )

    def gate(self, checkpoint_reader):
        return CommonPreWriteGate(
            journal=self.journal,
            trusted_head_reader=lambda: SHA,
            technical_verifier=lambda _: False,
            authority_verifier=lambda _: False,
            trusted_checkpoint_reader=checkpoint_reader,
        )

    def test_valid_independent_checkpoint_allows_only_blocker_preflight(self):
        result = self.gate(lambda: self.anchor).require_clear(
            logical_intent_id=INTENT, expected_head_sha=SHA,
        )
        self.assertTrue(result.no_active_blocker)
        self.assertFalse(result.write_authorized)

    def test_tail_deletion_is_not_seen_by_chain_alone_but_anchor_denies(self):
        from chatgpt_operation.repository.blocker_triage import (
            BlockerObservation, BlockerSource,
        )
        self.journal.record_blocker(BlockerObservation(
            BlockerSource.CI, INTENT, "connector", "blocker-2",
        ))
        anchored = self.journal.read()
        trusted_new_anchor = JournalCheckpoint(
            sequence=len(anchored.events), tip=anchored.tip,
            anchor_ref="independent-protected-checkpoint:237",
        )
        self.transport.comments.pop()
        # Remaining event chain is internally valid, but *truncated*.
        self.assertEqual(len(self.journal.read().events), 1)
        with self.assertRaisesRegex(BlockerGateError, "journal"):
            self.gate(lambda: trusted_new_anchor).require_clear(
                logical_intent_id=INTENT, expected_head_sha=SHA,
            )

    def test_entire_journal_deletion_detected(self):
        self.transport.comments.clear()
        with self.assertRaises(BlockerGateError):
            self.gate(lambda: self.anchor).require_clear(
                logical_intent_id=INTENT, expected_head_sha=SHA,
            )

    def test_new_unanchored_event_fails_until_external_checkpoint_advances(self):
        from chatgpt_operation.repository.blocker_triage import (
            BlockerObservation, BlockerSource,
        )
        self.journal.record_blocker(BlockerObservation(
            BlockerSource.UNKNOWN, INTENT, "connector", "unknown-2",
        ))
        with self.assertRaises(BlockerGateError):
            self.gate(lambda: self.anchor).require_clear(
                logical_intent_id=INTENT, expected_head_sha=SHA,
            )
        new = self.journal.read()
        fresh_anchor = JournalCheckpoint(
            sequence=len(new.events), tip=new.tip,
            anchor_ref="independently-updated-checkpoint",
        )
        # Updated anchor now matches history but unknown blocker remains active.
        with self.assertRaisesRegex(BlockerGateError, "ACTIVE_BLOCKER"):
            self.gate(lambda: fresh_anchor).require_clear(
                logical_intent_id=INTENT, expected_head_sha=SHA,
            )

    def test_unrelated_discussion_comment_does_not_affect_anchor(self):
        self.transport.comments.append({
            "id": 2, "body": "unrelated discussion", "user": {"login": "other"},
        })
        require_checkpoint(self.journal.read(), self.anchor)

    def test_unreadable_or_invalid_checkpoint_blocks(self):
        def unavailable():
            raise RuntimeError("anchor store unavailable")
        for reader in (unavailable, lambda: None):
            with self.subTest(reader=reader), self.assertRaises(BlockerGateError):
                self.gate(reader).require_clear(
                    logical_intent_id=INTENT, expected_head_sha=SHA,
                )
        for args in (
            (0, self.anchor.tip, "trusted"),
            (True, self.anchor.tip, "trusted"),
            (1, "0" * 64, "trusted"),
            (1, "g" * 64, "trusted"),
            (1, self.anchor.tip, ""),
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                JournalCheckpoint(*args)

    def test_wrong_count_or_tip_fails_even_with_valid_local_chain(self):
        for cp in (
            JournalCheckpoint(2, self.anchor.tip, "separate"),
            JournalCheckpoint(1, "f" * 64, "separate"),
        ):
            with self.subTest(cp=cp), self.assertRaises(JournalError):
                require_checkpoint(self.snapshot, cp)


if __name__ == "__main__":
    unittest.main()
