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

    def enroll(self):
        return self.journal.register_work(
            logical_intent_id=INTENT, exact_head_sha=HEAD,
            evidence_ref="controller-registered-work-236")

    def gate(self, *, head=HEAD, tech=None, authority=None):
        return CommonPreWriteGate(
            journal=self.journal, trusted_head_reader=lambda: head,
            technical_verifier=tech or (lambda _: False),
            authority_verifier=authority or (lambda _: False),
        )

    def test_empty_history_is_blocked_until_trusted_work_enrollment(self):
        r = self.gate().evaluate(logical_intent_id=INTENT, expected_head_sha=HEAD)
        self.assertFalse(r.no_active_blocker)
        self.assertEqual(r.reason, "WORK_REGISTRATION_NOT_ATTESTED")
        self.assertFalse(r.write_authorized)

    def test_registered_unblocked_work_can_pass_without_write_authority(self):
        self.enroll()
        r = self.gate().evaluate(logical_intent_id=INTENT, expected_head_sha=HEAD)
        self.assertTrue(r.no_active_blocker)
        self.assertFalse(r.write_authorized)
        self.assertEqual(r.checked_events, 1)

    def test_registration_cannot_be_rebound_to_new_head_or_receipt(self):
        self.enroll()
        with self.assertRaisesRegex(JournalError, "cannot be replaced"):
            self.journal.register_work(
                logical_intent_id=INTENT, exact_head_sha=OTHER_HEAD,
                evidence_ref="changed-work-origin")

    def test_persistent_issue_comment_read_after_new_journal_instance(self):
        self.enroll()
        after = self.journal.record_blocker(blocker())
        self.assertEqual(len(after.events), 2)
        self.assertEqual(self.api.writes, 2)
        recovered = GitHubIssueBlockerJournal(
            self.api, issue_number=236, trusted_actor="samuel-bot").read()
        self.assertEqual(recovered.tip, after.tip)
        self.assertEqual(recovered.events, after.events)
        with self.assertRaisesRegex(BlockerGateError, "ACTIVE_BLOCKER"):
            self.gate().require_clear(logical_intent_id=INTENT, expected_head_sha=HEAD)

    def test_safety_denial_never_cleared_by_technical_attestation(self):
        self.enroll()
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
        self.enroll()
        b = blocker(source=BlockerSource.CI)
        self.journal.record_blocker(b)
        self.journal.record_clearance(proof(ClearanceKind.EXACT_HEAD_CI_PASS))
        self.assertTrue(self.gate(tech=lambda _: True).evaluate(
            logical_intent_id=INTENT, expected_head_sha=HEAD).no_active_blocker)
        self.assertFalse(self.gate(head=OTHER_HEAD, tech=lambda _: True).evaluate(
            logical_intent_id=INTENT, expected_head_sha=OTHER_HEAD).no_active_blocker)

    def test_access_denial_requires_exact_permission_recovery_evidence(self):
        self.enroll()
        b = BlockerObservation(BlockerSource.GITHUB_HTTP, INTENT, "connector", "deny-1", 403)
        self.journal.record_blocker(b)
        self.journal.record_clearance(proof(ClearanceKind.TARGET_ACCESS_RESTORED))
        self.assertFalse(self.gate().evaluate(logical_intent_id=INTENT, expected_head_sha=HEAD).no_active_blocker)
        self.assertTrue(self.gate(tech=lambda _: True).evaluate(
            logical_intent_id=INTENT, expected_head_sha=HEAD).no_active_blocker)

    def test_a_second_uncleared_blocker_still_blocks(self):
        self.enroll()
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
        self.enroll()
        self.journal.record_blocker(blocker())
        new_scope = logical_intent_id(
            repository="HyungseonSong-plasma/chatgpt-operation",
            branch="samuel/236-new-branch", work_id="owner-issued-236",
            paths=("src/renamed.py",))
        self.assertEqual(INTENT, new_scope)
        self.assertFalse(self.gate().evaluate(
            logical_intent_id=new_scope, expected_head_sha=HEAD).no_active_blocker)


class BlockingTransport:
    def __init__(self):
        self.calls = []
    def get(self, *a, **k):
        self.calls.append(("GET", a))
        raise AssertionError("unexpected repository read before blocker clearance")
    def request(self, *a, **k):
        self.calls.append(("WRITE", a))
        raise AssertionError("unexpected repository write after blocker rejection")


class MutationEntrypointIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.api = IssueAPI()
        self.journal = GitHubIssueBlockerJournal(
            self.api, issue_number=236, trusted_actor="samuel-bot")
        self.journal.register_work(
            logical_intent_id=INTENT, exact_head_sha=HEAD,
            evidence_ref="controller-registered-work-236")
        self.journal.record_blocker(blocker())
        self.gate = CommonPreWriteGate(
            journal=self.journal, trusted_head_reader=lambda: HEAD,
            technical_verifier=lambda _: False, authority_verifier=lambda _: False,
        )

    def test_repository_mutation_engine_refuses_before_file_api(self):
        from chatgpt_operation.repository.mutation import (
            Engine, HardStop, parse_policy, parse_manifest,
        )
        repo = "HyungseonSong-plasma/chatgpt-operation"
        policy = parse_policy({
            "schema_version": 1, "repository": repo,
            "mutation": {
                "allow": {"file": ["create"], "branch": ["create"]},
                "file_paths": {"allow": ["docs/**"], "deny": [".github/**"]},
                "branch_names": {"allow": ["samuel/*"], "deny": ["main"]},
            },
            "validation_gate": {"mode": "off", "workflows": [], "ignore_current_run": False},
        })
        manifest = parse_manifest({
            "schema_version": 1, "repository": repo, "resource": "file",
            "action": "create",
            "target": {"path": "docs/test.md", "branch": "samuel/example"},
            "expected": {"absent": True}, "desired": {"content": "hello"},
            "commit_message": "test",
        })
        transport = BlockingTransport()
        engine = Engine(
            transport, repository=repo, policy=policy,
            blocker_gate=self.gate, trusted_work_id="owner-issued-236",
            trusted_head_sha=HEAD,
        )
        with self.assertRaisesRegex(HardStop, "common prewrite gate"):
            engine.execute(manifest)
        self.assertEqual(transport.calls, [])

    def test_native_github_execution_kernel_refuses_before_provider(self):
        from chatgpt_operation.controller.action_plan import ActionPlan
        from chatgpt_operation.controller.research import ResearchState, ResearchStage
        from chatgpt_operation.github.execution_kernel import (
            ExecutionKernel, ExecutionKernelError, ExecutionProvider, GitHubCapability,
        )
        from chatgpt_operation.github.native_executor import NativeGitHubAction
        plan = ActionPlan.from_dict({
            "schema_version": 1, "research_id": "samuel-test",
            "stage": "execute", "executor": "github_native",
            "payload": {
                "action": "merge_pr",
                "repository": "HyungseonSong-plasma/chatgpt-operation",
                "target": {"number": 237, "expected_head_sha": HEAD},
                "desired_postcondition": {"merged": True},
            },
            "expected_observation": "merged",
        })
        provider = ExecutionProvider(
            name="github-connector",
            capabilities=frozenset({GitHubCapability.MERGE_PR}),
            read_state=lambda *_: self.fail("provider read must not occur"),
            mutate=lambda *_: self.fail("provider mutation must not occur"),
        )
        kernel = ExecutionKernel(
            [provider],
            state=ResearchState("samuel-test", "gate test", stage=ResearchStage.EXECUTE),
            blocker_gate=self.gate, trusted_work_id="owner-issued-236",
            trusted_head_sha=HEAD,
        )
        with self.assertRaisesRegex(ExecutionKernelError, "common prewrite gate"):
            kernel.execute(plan)

    def test_native_gate_requires_trusted_work_identity(self):
        from chatgpt_operation.controller.action_plan import ActionPlan
        from chatgpt_operation.controller.research import ResearchState, ResearchStage
        from chatgpt_operation.github.execution_kernel import (
            ExecutionKernel, ExecutionKernelError, ExecutionProvider, GitHubCapability,
        )
        plan = ActionPlan.from_dict({
            "schema_version": 1, "research_id": "samuel-test",
            "stage": "execute", "executor": "github_native",
            "payload": {
                "action": "merge_pr",
                "repository": "HyungseonSong-plasma/chatgpt-operation",
                "target": {"number": 237, "expected_head_sha": HEAD},
                "desired_postcondition": {"merged": True},
            },
            "expected_observation": "merged",
        })
        provider = ExecutionProvider(
            name="github-connector",
            capabilities=frozenset({GitHubCapability.MERGE_PR}),
            read_state=lambda *_: self.fail("provider read before identity attestation"),
            mutate=lambda *_: self.fail("provider write without identity attestation"),
        )
        kernel = ExecutionKernel(
            [provider],
            state=ResearchState("samuel-test", "gate test", stage=ResearchStage.EXECUTE),
            blocker_gate=self.gate,
        )
        with self.assertRaisesRegex(ExecutionKernelError, "trusted native work/head identity missing"):
            kernel.execute(plan)


if __name__ == "__main__":
    unittest.main()
