"""Adversarial governed codeQA write proof tests; no network or live writes."""
from __future__ import annotations

import base64
from copy import deepcopy
from dataclasses import replace
import unittest

from chatgpt_operation.controller.codeqa_governed_write import (
    SOURCE, TARGET, HEAD, PATH, POLICY_ID, WORK_ID,
    check_policy, build_governed_write_proof,
    execute_branch_and_file, repository_policy, CodeQAWriteError,
)
from chatgpt_operation.repository.mutation import ApiError, parse_policy

BASE = "a" * 40
SOURCE_SHA = "b" * 40


def candidate(enabled=True):
    return {
        "schema_version": 1, "policy_id": POLICY_ID, "enabled": enabled,
        "repository": TARGET, "repository_id": 1424293498,
        "base_branch": "main", "head_branch": HEAD, "base_sha": BASE,
        "path_prefixes": ["docs/samuel/"], "workflows": ["layout.yml"],
        "operations": ["branch.create", "file.create", "pr.create", "ci.inspect"],
        "merge_enabled": False,
        "authorization_source":
            "OWNER_REVIEW_AND_INDEPENDENT_GITHUB_WORKFLOW_ATTESTATION_REQUIRED",
        "credential_name": "SAMUEL_CODEQA_WRITE_TOKEN",
    }


def issue(repo, number):
    return {
        "number": number, "state": "open",
        "url": f"https://api.github.com/repos/{repo}/issues/{number}",
    }


def source_run():
    return {
        "id": 123, "event": "workflow_dispatch", "head_branch": "main",
        "head_sha": SOURCE_SHA,
        "path": ".github/workflows/samuel-codeqa-write-execute.yml",
        "actor": {"login": "HyungseonSong-plasma"},
        "repository": {"full_name": SOURCE},
    }


class Reader:
    def __init__(self):
        self.calls = []
        self.data = {
            "/repos/" + TARGET: {
                "id": 1424293498, "full_name": TARGET,
                "default_branch": "main", "permissions": {"push": True},
            },
            "/repos/" + TARGET + "/git/ref/heads/main": {
                "ref": "refs/heads/main", "object": {"sha": BASE},
            },
            "/repos/" + TARGET + "/actions/workflows/layout.yml": {
                "path": ".github/workflows/layout.yml", "state": "active",
            },
        }

    def get(self, path):
        self.calls.append(path)
        return self.data[path]


def make_proof(**overrides):
    args = dict(
        policy=candidate(), controller_run=source_run(),
        source_issue=issue(SOURCE, 220), target_issue=issue(TARGET, 92),
        observed_run_id=123, observed_source_sha=SOURCE_SHA,
        target_reader=Reader(),
    )
    args.update(overrides)
    return build_governed_write_proof(**args)


class FakeRepositoryTransport:
    def __init__(self):
        self.branch = None
        self.content = None
        self.writes = []

    def get(self, path, *, query=None):
        if path == "/git/ref/heads/" + HEAD:
            if self.branch is None:
                raise ApiError("not found", status=404)
            return {"ref": "refs/heads/" + HEAD, "object": {"sha": self.branch}}
        if path == "/contents/" + PATH:
            if self.content is None:
                raise ApiError("not found", status=404)
            return {
                "sha": "c" * 40, "content": base64.b64encode(self.content.encode()).decode(),
                "encoding": "base64",
            }
        raise AssertionError("unexpected read " + path)

    def request(self, method, path, *, payload=None):
        self.writes.append((method, path, payload))
        if method == "POST" and path == "/git/refs":
            self.branch = payload["sha"]
            return {"ref": payload["ref"], "object": {"sha": payload["sha"]}}
        if method == "PUT" and path == "/contents/" + PATH:
            self.content = base64.b64decode(payload["content"]).decode()
            self.branch = "d" * 40  # GitHub content writes advance branch HEAD.
            return {"content": {"sha": "c" * 40}}
        raise AssertionError("unexpected write " + method + " " + path)


class GovernedWriteTests(unittest.TestCase):
    def test_fixed_scope_produces_three_typed_plans(self):
        proof = make_proof()
        self.assertEqual(proof.controller_run_id, 123)
        self.assertEqual(proof.target_base_sha, BASE)
        self.assertEqual(proof.branch_plan.executor.value, "repository_mutation")
        self.assertEqual(proof.branch_plan.payload["target"], {"name": HEAD})
        self.assertEqual(proof.file_plan.payload["target"], {"path": PATH, "branch": HEAD})
        self.assertEqual(proof.pr_plan.executor.value, "github_native")
        self.assertEqual(proof.pr_plan.payload["target"]["base"], "main")
        self.assertNotIn("merge_pr", str(proof.pr_plan.payload))

    def test_disabled_write_candidate_cannot_create_plan_or_issue_api_reads(self):
        reader = Reader()
        with self.assertRaises(CodeQAWriteError):
            make_proof(policy=candidate(False), target_reader=reader)
        self.assertEqual(reader.calls, [])

    def test_broadened_policy_denied(self):
        controls = [
            ("repository", SOURCE), ("repository_id", 12), ("base_branch", "release"),
            ("head_branch", "main"), ("path_prefixes", ["src/"]),
            ("workflows", ["layout.yml", "other.yml"]),
            ("operations", ["branch.create", "pr.merge"]),
            ("merge_enabled", True), ("credential_name", "GITHUB_TOKEN"),
        ]
        for name, replacement in controls:
            with self.subTest(name=name):
                modified = candidate()
                modified[name] = replacement
                with self.assertRaises(CodeQAWriteError):
                    check_policy(modified)

    def test_stale_base_and_source_run_denied(self):
        for path, value in [
            ("controller_run", {**source_run(), "event": "pull_request"}),
            ("controller_run", {**source_run(), "head_branch": "feature"}),
            ("controller_run", {**source_run(), "path": ".github/workflows/other.yml"}),
            ("controller_run", {**source_run(), "actor": {"login": "attacker"}}),
            ("observed_run_id", 124),
            ("observed_source_sha", "c" * 40),
        ]:
            with self.subTest(path=path):
                with self.assertRaises(CodeQAWriteError):
                    make_proof(**{path: value})
        r = Reader()
        r.data["/repos/" + TARGET + "/git/ref/heads/main"]["object"]["sha"] = "d" * 40
        with self.assertRaisesRegex(CodeQAWriteError, "live-readback"):
            make_proof(target_reader=r)

    def test_live_issues_must_both_be_real_and_open(self):
        for path, repo, number in (
            ("source_issue", SOURCE, 220), ("target_issue", TARGET, 92),
        ):
            with self.subTest(path=path):
                changed = issue(repo, number)
                changed["state"] = "closed"
                with self.assertRaises(CodeQAWriteError):
                    make_proof(**{path: changed})
                changed = issue(repo, number)
                changed["pull_request"] = {"url": "unexpected"}
                with self.assertRaises(CodeQAWriteError):
                    make_proof(**{path: changed})

    def test_branch_file_engine_and_readback(self):
        p = make_proof()
        transport = FakeRepositoryTransport()
        result = execute_branch_and_file(p, transport=transport)
        self.assertEqual([v["status"] for v in result], ["PASS", "PASS"])
        self.assertEqual(transport.branch, 'd' * 40)
        self.assertIn("Source workflow run: 123", transport.content)
        self.assertEqual([v[:2] for v in transport.writes], [
            ("POST", "/git/refs"), ("PUT", "/contents/" + PATH),
        ])

    def test_replay_branch_with_changed_content_is_rejected(self):
        p = make_proof()
        t = FakeRepositoryTransport()
        execute_branch_and_file(p, transport=t)
        with self.assertRaisesRegex(Exception, "different head"):
            execute_branch_and_file(p, transport=t)

    def test_dedicated_repo_mutation_policy_does_not_authorize_main_or_source(self):
        policy = parse_policy(repository_policy())
        self.assertEqual(policy.repository, TARGET)
        self.assertNotIn("update", policy.allow_file_actions)
        self.assertNotIn("delete", policy.allow_file_actions)
        self.assertEqual(policy.branch_allow, (HEAD,))
