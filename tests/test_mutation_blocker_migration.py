"""Historical denial migration regressions for registered legacy work."""
import unittest

from chatgpt_operation.repository.blocker_gate import CommonPreWriteGate, BlockerGateError
from chatgpt_operation.repository.blocker_journal import GitHubIssueBlockerJournal
from chatgpt_operation.repository.blocker_migration import (
    HistoricalBlockerInventory, HistoricalMigrationError, reconcile_legacy_blockers,
)
from chatgpt_operation.repository.blocker_triage import (
    BlockerObservation, BlockerSource, logical_intent_id,
)

REPO = "HyungseonSong-plasma/codeQA"
HEAD = "e" * 40
INTENT = logical_intent_id(
    repository=REPO, branch="feat/93-scoped-parser-integration-20261026",
    work_id="codeqa-93-source-integration",
    paths=("src/codeqa/adapters/cpp_parser_evidence.py",),
)


class API:
    def __init__(self):
        self.comments = []
        self.fail_next_write = False

    def get(self, path, *, query=None):
        if path != "/issues/236/comments":
            raise AssertionError(path)
        page = int(query["page"])
        offset = (page - 1) * 100
        return [dict(x) for x in self.comments[offset:offset + 100]]

    def request(self, method, path, *, payload=None):
        if self.fail_next_write:
            self.fail_next_write = False
            raise OSError("write failed")
        if method != "POST" or path != "/issues/236/comments":
            raise AssertionError("unexpected request")
        comment = {"id": len(self.comments) + 1, "body": payload["body"],
                   "user": {"login": "trusted-journal-actor"}}
        self.comments.append(comment)
        return dict(comment)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.api = API()
        self.journal = GitHubIssueBlockerJournal(
            self.api, issue_number=236, trusted_actor="trusted-journal-actor",
        )
        self.first = BlockerObservation(
            BlockerSource.TOOL_SAFETY, INTENT, "github-connector",
            "original-tool-screening-denial-receipt",
        )
        self.second = BlockerObservation(
            BlockerSource.STALE_IDENTITY, INTENT, "github-connector",
            "later-stale-head-diagnostic",
        )
        self.inv = HistoricalBlockerInventory(
            INTENT, "trusted-source-index-236",
            "independent-history-completeness-proof", (self.first, self.second),
        )

    def migrate(self, inventory=None, verifier=None):
        return reconcile_legacy_blockers(
            self.journal,
            inventory=self.inv if inventory is None else inventory,
            exact_head_sha=HEAD,
            registration_evidence_ref="trusted-controller-migration-complete",
            trusted_inventory_verifier=(lambda _: True) if verifier is None else verifier,
        )

    def test_historical_denials_persist_before_registration(self):
        result = self.migrate()
        events = [e["payload"] for e in result.events]
        self.assertEqual(
            [e["event"] for e in events],
            ["BLOCKED", "BLOCKED", "REGISTERED"],
        )
        self.assertEqual(events[0]["source"], "tool_safety")
        self.assertEqual(events[-1]["intent"], INTENT)

    def test_migrated_safety_denial_remains_active_under_gate(self):
        self.migrate()
        gate = CommonPreWriteGate(
            journal=self.journal, trusted_head_reader=lambda: HEAD,
            technical_verifier=lambda _: True,
            authority_verifier=lambda _: False,
        )
        with self.assertRaisesRegex(BlockerGateError, "ACTIVE_BLOCKER_TOOL_SAFETY"):
            gate.require_clear(logical_intent_id=INTENT, expected_head_sha=HEAD)

    def test_no_completeness_verifier_rejects_without_journal_write(self):
        with self.assertRaisesRegex(HistoricalMigrationError, "completeness verifier"):
            reconcile_legacy_blockers(
                self.journal, inventory=self.inv, exact_head_sha=HEAD,
                registration_evidence_ref="enroll", trusted_inventory_verifier=None,
            )
        self.assertEqual(len(self.api.comments), 0)

    def test_false_exception_and_nonboolean_attestation_fail_closed(self):
        def crash(_):
            raise RuntimeError("source inaccessible")
        for verify in (lambda _: False, lambda _: 1, lambda _: "PASS", crash):
            with self.subTest(verify=verify):
                with self.assertRaises(HistoricalMigrationError):
                    self.migrate(verifier=verify)
                self.assertEqual(self.journal.read().events, ())

    def test_empty_inventory_is_not_trusted_legacy_enrollment(self):
        with self.assertRaisesRegex(ValueError, "empty history"):
            HistoricalBlockerInventory(INTENT, "source", "completeness", ())

    def test_mixed_work_or_ambiguous_blocker_rejected(self):
        another = logical_intent_id(
            repository=REPO, branch="other", work_id="different-work",
            paths=("docs/other.md",),
        )
        with self.assertRaisesRegex(ValueError, "same work"):
            HistoricalBlockerInventory(
                INTENT, "source", "proof", (
                    BlockerObservation(BlockerSource.CI, another, "connector", "wrong"),
                ),
            )
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            HistoricalBlockerInventory(INTENT, "source", "proof", (self.first, self.first))

    def test_interrupted_migration_can_replay_without_duplicate_denials(self):
        self.journal.record_blocker(self.first)
        result = self.migrate()
        self.assertEqual(len(result.events), 3)
        self.assertEqual(
            [x["payload"]["evidence_ref"] for x in result.events
             if x["payload"]["event"] == "BLOCKED"],
            [self.first.evidence_ref, self.second.evidence_ref],
        )

    def test_conflicting_evidence_ref_cannot_launder_prior_denial(self):
        existing = BlockerObservation(
            BlockerSource.REPOSITORY_POLICY, INTENT, "other-provider",
            self.first.evidence_ref,
        )
        self.journal.record_blocker(existing)
        with self.assertRaisesRegex(HistoricalMigrationError, "conflict"):
            self.migrate()
        self.assertFalse(any(
            e["payload"]["event"] == "REGISTERED"
            for e in self.journal.read().events
        ))

    def test_registration_before_migration_cannot_be_retroactively_approved(self):
        self.journal.register_work(
            logical_intent_id=INTENT, exact_head_sha=HEAD,
            evidence_ref="premature-registration",
        )
        with self.assertRaisesRegex(HistoricalMigrationError, "registered before"):
            self.migrate()

    def test_failed_import_never_registers_work(self):
        self.api.fail_next_write = True
        with self.assertRaises(HistoricalMigrationError):
            self.migrate()
        self.assertEqual(len(self.journal.read().events), 0)

    def test_branch_path_changes_keep_same_history_identity(self):
        other_scope = logical_intent_id(
            repository=REPO, branch="changed-branch",
            work_id="codeqa-93-source-integration", paths=("docs/alternate.md",),
        )
        self.assertEqual(other_scope, INTENT)
        self.migrate()
        gate = CommonPreWriteGate(
            journal=self.journal, trusted_head_reader=lambda: HEAD,
            technical_verifier=lambda _: False, authority_verifier=lambda _: False,
        )
        with self.assertRaises(BlockerGateError):
            gate.require_clear(logical_intent_id=other_scope, expected_head_sha=HEAD)


if __name__ == "__main__":
    unittest.main()
