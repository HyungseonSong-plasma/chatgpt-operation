"""#264 trusted exact-SHA consumer policy acquisition: no live writes."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from chatgpt_operation.controller.action_lifecycle import DispatchIntent
from chatgpt_operation.controller.action_plan import ActionPlan
from chatgpt_operation.controller.execution_gateway import (
    ExecutionGateway, ExecutionGatewayError,
)
from chatgpt_operation.repository.mutation import PolicyError, parse_manifest
from chatgpt_operation.repository.target_policy_preflight import (
    CONSUMER_WORKFLOW,
    POLICY_PATH,
    SAMUEL_REPOSITORY,
    require_target_mutation_policy,
)

CONSUMER = "HyungseonSong-plasma/codeQA"
HEAD = "a" * 40
OTHER = "b" * 40


def policy(repository=CONSUMER):
    return {
        "schema_version": 1,
        "repository": repository,
        "mutation": {
            "allow": {"file": ["create", "update"], "branch": ["create"]},
            "file_paths": {
                "allow": ["src/**", "tests/**", "docs/**"],
                "deny": [".github/workflows/**", "automation/**"],
            },
            "branch_names": {
                "allow": ["samuel/*", "issue-*"], "deny": ["main"],
            },
        },
        "validation_gate": {
            "mode": "named_workflows",
            "workflows": ["CI"],
            "ignore_current_run": True,
        },
    }


def manifest(repository=CONSUMER, branch="issue-264-compat", action="update", path="docs/qa.md"):
    if action == "branch-create":
        raw = {
            "schema_version": 1, "repository": repository,
            "resource": "branch", "action": "create",
            "target": {"name": branch},
            "expected": {"absent": True},
            "desired": {"sha": HEAD},
        }
    else:
        raw = {
            "schema_version": 1, "repository": repository,
            "resource": "file", "action": action,
            "target": {"path": path, "branch": branch},
            "expected": {"absent": True} if action == "create" else {"sha": OTHER},
            "desired": {"content": "test"},
            "commit_message": "test",
        }
    return parse_manifest(raw)


def plan(m):
    return ActionPlan.from_dict({
        "schema_version": 1,
        "research_id": "policy-binding-readonly",
        "stage": "execute",
        "executor": "repository_mutation",
        "payload": {
            "schema_version": 1, "repository": m.repository,
            "resource": m.resource, "action": m.action,
            "target": m.target, "expected": m.expected, "desired": m.desired,
            **({"commit_message": m.commit_message} if m.commit_message else {}),
        },
        "expected_observation": "no real mutation",
    })


def intent(p, sha=HEAD, ref="main", workflow=CONSUMER_WORKFLOW):
    return DispatchIntent(
        action_id=p.idempotency_key, research_id=p.research_id,
        workflow=workflow, ref=ref,
        requested_at="2026-11-06T17:40:00Z", state_revision=2,
        expected_head_sha=sha,
    )


class FakeConsumerTransport:
    def __init__(self, repository=CONSUMER, document=None):
        self.repository = repository
        self.document = policy() if document is None else document
        self.current_sha = HEAD
        self.next_sha = None
        self.omit_policy = False
        self.bad_blob = False
        self.bad_size = False
        self.bad_path = False
        self.bad_encoding = False
        self.truncated_base64 = False
        self.raw = None
        self.gets = []
        self.writes = []

    def get(self, path, *, query=None):
        self.gets.append((path, query))
        if path == "/git/ref/heads/main":
            if self.next_sha is not None and sum(
                p == "/git/ref/heads/main" for p, _ in self.gets
            ) > 1:
                return {"ref": "refs/heads/main",
                        "object": {"type": "commit", "sha": self.next_sha}}
            return {"ref": "refs/heads/main",
                    "object": {"type": "commit", "sha": self.current_sha}}
        if path == "/contents/" + POLICY_PATH:
            if self.omit_policy:
                raise LookupError("404 no consumer policy")
            assert query == {"ref": HEAD}, "policy must be pinned to exact main HEAD"
            data = self.raw if self.raw is not None else json.dumps(
                self.document, sort_keys=True, separators=(",", ":")
            ).encode()
            b64 = base64.b64encode(data).decode("ascii")
            if self.truncated_base64:
                b64 = b64[:-1]
            git_blob = b"blob " + str(len(data)).encode("ascii") + b"\0" + data
            return {
                "type": "file",
                "path": POLICY_PATH + (".other" if self.bad_path else ""),
                "encoding": "utf-8" if self.bad_encoding else "base64",
                "content": b64,
                "sha": "c" * 40 if self.bad_blob else hashlib.sha1(git_blob).hexdigest(),
                "size": len(data) + int(self.bad_size),
            }
        raise AssertionError("unexpected trusted API read " + path)

    def request(self, method, path, *, payload=None):
        self.writes.append((method, path, payload))
        raise AssertionError("mutation/dispatch must not be attempted in preflight")


class ConsumerPolicyTests(unittest.TestCase):
    def setUp(self):
        self.m = manifest()
        self.transport = FakeConsumerTransport()

    def verify(self, m=None, transport=None, **kwargs):
        return require_target_mutation_policy(
            manifest=self.m if m is None else m,
            transport=self.transport if transport is None else transport,
            branch=(self.m if m is None else m).target.get(
                "branch", (self.m if m is None else m).target.get("name")
            ),
            expected_main_sha=kwargs.pop("expected_main_sha", HEAD),
            dispatch_ref=kwargs.pop("dispatch_ref", "main"),
            workflow=kwargs.pop("workflow", CONSUMER_WORKFLOW),
            **kwargs,
        )

    def test_consumer_target_pinned_policy_accepts_bounded_file_update(self):
        self.assertEqual(self.verify(), "issue-264-compat")
        self.assertEqual(self.transport.gets, [
            ("/git/ref/heads/main", None),
            ("/contents/" + POLICY_PATH, {"ref": HEAD}),
            ("/git/ref/heads/main", None),
        ])
        self.assertFalse(self.transport.writes)

    def test_consumer_policy_applies_to_file_create_and_branch_create(self):
        for action in ("create", "branch-create"):
            with self.subTest(action=action):
                transport = FakeConsumerTransport()
                self.assertEqual(
                    self.verify(manifest(action=action), transport), "issue-264-compat"
                )
                self.assertFalse(transport.writes)

    def test_wrong_repo_cannot_use_samuel_or_consumer_policy(self):
        for repo in (SAMUEL_REPOSITORY, "other/unrelated"):
            with self.subTest(repo=repo), self.assertRaisesRegex(
                PolicyError, "transport repository"
            ):
                self.verify(transport=FakeConsumerTransport(repository=repo))
        self.assertFalse(self.transport.gets)

    def test_missing_consumer_policy_fails_closed(self):
        self.transport.omit_policy = True
        with self.assertRaisesRegex(PolicyError, "policy unsupported"):
            self.verify()
        self.assertFalse(self.transport.writes)

    def test_stale_or_invalid_revision_fails_before_policy_read(self):
        for sha in (OTHER, "main", "B" * 40):
            with self.subTest(sha=sha):
                transport = FakeConsumerTransport()
                with self.assertRaises(PolicyError):
                    self.verify(transport=transport, expected_main_sha=sha)
                self.assertNotIn(
                    "/contents/" + POLICY_PATH, [p for p, _ in transport.gets]
                )

    def test_main_change_during_pinned_policy_read_fails(self):
        self.transport.next_sha = OTHER
        with self.assertRaisesRegex(PolicyError, "changed during preflight"):
            self.verify()

    def test_mismatched_policy_repository_fails(self):
        self.transport.document["repository"] = SAMUEL_REPOSITORY
        with self.assertRaisesRegex(PolicyError, "binding mismatch"):
            self.verify()

    def test_malformed_duplicate_or_changed_evidence_denied(self):
        failures = ("bad_blob", "bad_size", "bad_path", "bad_encoding", "truncated_base64")
        for attr in failures:
            with self.subTest(attr=attr):
                t = FakeConsumerTransport()
                setattr(t, attr, True)
                with self.assertRaises(PolicyError):
                    self.verify(transport=t)
                self.assertFalse(t.writes)
        for raw in (b"{invalid", b'{"schema_version":1,"schema_version":1}',
                    b"\xff\xfe"):
            with self.subTest(raw=raw):
                t = FakeConsumerTransport()
                t.raw = raw
                with self.assertRaises(PolicyError):
                    self.verify(transport=t)

    def test_invalid_policy_schema_and_path_deny_fail_closed(self):
        for key in ("mutation", "validation_gate", "repository"):
            doc = policy()
            doc.pop(key)
            with self.subTest(key=key), self.assertRaises(PolicyError):
                self.verify(transport=FakeConsumerTransport(document=doc))
        for path in ("automation/samuel/repository-mutation-policy.json",
                     ".github/workflows/forbidden.yml", "private/secret.txt"):
            with self.subTest(path=path), self.assertRaises(PolicyError):
                self.verify(manifest(path=path))

    def test_forbidden_branches_or_actions_denied(self):
        for branch in ("main", "feat/denied", "issue-264/../main"):
            m = manifest(branch=branch) if ".." not in branch else None
            if m is not None:
                with self.subTest(branch=branch), self.assertRaises(PolicyError):
                    self.verify(m)
        self.transport.document["mutation"]["allow"]["file"] = ["create"]
        with self.assertRaisesRegex(PolicyError, "file action denied"):
            self.verify()

    def test_consumer_needs_known_main_workflow(self):
        for kw in ({"dispatch_ref": "feature"}, {"workflow": "other.yml"}):
            with self.subTest(kw=kw), self.assertRaisesRegex(
                PolicyError, "untrusted dispatch"
            ):
                self.verify(**kw)
        self.assertFalse(self.transport.gets)

    def test_samuel_policy_keeps_existing_branch_semantics(self):
        original = policy(SAMUEL_REPOSITORY)
        with TemporaryDirectory() as tmp:
            file = Path(tmp) / "policy.json"
            file.write_text(json.dumps(original), encoding="utf-8")
            m = manifest(repository=SAMUEL_REPOSITORY, branch="issue-264-compat")
            t = FakeConsumerTransport(repository=SAMUEL_REPOSITORY)
            self.assertEqual(self.verify(m, t, samuel_local_policy_path=file),
                             "issue-264-compat")
            denied = manifest(repository=SAMUEL_REPOSITORY, branch="feat/not-allowed")
            with self.assertRaisesRegex(PolicyError, "branch name denied"):
                self.verify(denied, t, samuel_local_policy_path=file)
            self.assertEqual(t.gets, [])

    @patch("chatgpt_operation.controller.execution_gateway.dispatch_workflow")
    def test_gateway_denies_consumer_without_policy_before_dispatch(self, dispatch):
        self.transport.omit_policy = True
        p = plan(self.m)
        with self.assertRaisesRegex(
            ExecutionGatewayError, "consumer repository policy unsupported"
        ):
            ExecutionGateway(self.transport)._dispatch_action_plan(p, intent(p))
        dispatch.assert_not_called()
        self.assertFalse(self.transport.writes)

    @patch("chatgpt_operation.controller.execution_gateway.dispatch_workflow")
    def test_gateway_consumer_bounded_readonly_smoke_uses_existing_dispatch(self, dispatch):
        p = plan(self.m)
        dispatch.return_value = {"workflow_run_id": 19}
        result = ExecutionGateway(self.transport)._dispatch_action_plan(p, intent(p))
        self.assertEqual(result["workflow_run_id"], 19)
        dispatch.assert_called_once()
        self.assertEqual(self.transport.writes, [])  # dispatch is a mock, no write

    @patch("chatgpt_operation.controller.execution_gateway.dispatch_workflow")
    def test_gateway_wrong_transport_repo_cannot_cross_dispatch(self, dispatch):
        p = plan(self.m)
        t = FakeConsumerTransport(repository=SAMUEL_REPOSITORY)
        with self.assertRaisesRegex(
            ExecutionGatewayError, "dispatch transport repository"
        ):
            ExecutionGateway(t)._dispatch_action_plan(p, intent(p))
        dispatch.assert_not_called()
        self.assertEqual(t.gets, [])


if __name__ == "__main__":
    unittest.main()
