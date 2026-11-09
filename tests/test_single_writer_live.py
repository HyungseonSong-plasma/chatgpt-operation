"""Strict live GitHub state-writer attestation: read-only failure-injection tests."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import unittest
from zipfile import ZIP_DEFLATED, ZipFile

from chatgpt_operation.controller.single_writer_live import (
    LiveEvidenceError, read_stable_issue_comments,
    verify_github_progress_source, qualify_next_inbox_request,
)
from chatgpt_operation.controller.single_writer_pilot import (
    create_intent, plan_progress_write, encode_inbox_comment,
)
from chatgpt_operation.controller.durable_state import encode_state
from chatgpt_operation.controller.progress_resume import (
    attach_checkpoint, create_checkpoint, detail_digest,
)
from chatgpt_operation.controller.research import ResearchState


REPO = "HyungseonSong-plasma/chatgpt-operation"
WORKFLOW = "samuel-progress-evidence.yml"
HEAD = "a" * 40
RUN_ID = 1234
ARTIFACT_ID = 4321


def sha(data):
    return hashlib.sha256(data).hexdigest()


def archive_bytes(manifest, *, extra=False):
    stream = io.BytesIO()
    with ZipFile(stream, "w", compression=ZIP_DEFLATED) as out:
        out.writestr("progress-evidence.json", json.dumps(manifest, sort_keys=True))
        if extra:
            out.writestr("surprise.txt", "UNEXPECTED")
    return stream.getvalue()


def fixture():
    detail = {
        "path": "docs/fixture.md",
        "line_count": 3,
        "references": ["../README.md"],
    }
    manifest = {
        "schema_version": 1,
        "work_id": "issue:qualification",
        "unit_id": "docs/fixture.md",
        "input_sha256": sha(b"test-source"),
        "outcome": "PASS",
        "detail_sha256": detail_digest(detail),
        "detail": detail,
        "head_sha": HEAD,
        "workflow_run_id": RUN_ID,
        "run_attempt": 1,
        "plan_sha256": sha(b"plan"),
        "policy_sha256": sha(b"policy"),
    }
    archive = archive_bytes(manifest)
    source = {
        "repository": REPO,
        "workflow": WORKFLOW,
        "run_id": RUN_ID,
        "head_sha": HEAD,
        "artifact_sha256": sha(archive),
    }
    intent = create_intent(
        work_id=manifest["work_id"],
        base_revision=2,
        plan_sha256=manifest["plan_sha256"],
        policy_sha256=manifest["policy_sha256"],
        unit_id=manifest["unit_id"],
        input_sha256=manifest["input_sha256"],
        outcome="PASS",
        detail=detail,
        source=source,
    )
    run = {
        "id": RUN_ID,
        "repository": {"full_name": REPO},
        "actor": {"login": "HyungseonSong-plasma"},
        "event": "workflow_dispatch",
        "head_branch": "main",
        "head_sha": HEAD,
        "path": ".github/workflows/" + WORKFLOW + "@refs/heads/main",
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 1,
    }
    artifact = {
        "total_count": 1,
        "artifacts": [{
            "id": ARTIFACT_ID,
            "name": f"samuel-progress-evidence-{RUN_ID}",
            "expired": False,
            "workflow_run": {"id": RUN_ID},
            "digest": "sha256:" + sha(archive),
        }],
    }
    return intent, run, artifact, archive, manifest


class GithubTransport:
    def __init__(self, run=None, artifacts=None, comments=None):
        self.run = run
        self.artifacts = artifacts
        self.comments = comments if comments is not None else []
        self.calls = []
        self.unstable = False

    def get(self, path, *, query=None):
        self.calls.append((path, query))
        if path.endswith(f"/actions/runs/{RUN_ID}"):
            return copy.deepcopy(self.run)
        if path.endswith(f"/actions/runs/{RUN_ID}/artifacts"):
            return copy.deepcopy(self.artifacts)
        if path == "/issues/44/comments":
            page = int(query["page"])
            data = self.comments[:]
            if self.unstable and len(self.calls) > 1:
                data.append({
                    "id": 9999999,
                    "body": "changed while listing",
                    "user": {"login": "github-actions[bot]"},
                })
            return copy.deepcopy(data[(page - 1) * 100:page * 100])
        raise AssertionError("unexpected GitHub read " + path)


def verified(intent=None, run=None, artifacts=None, archive=None):
    standard_intent, standard_run, standard_artifact, standard_archive, _ = fixture()
    intent = standard_intent if intent is None else intent
    transport = GithubTransport(
        standard_run if run is None else run,
        standard_artifact if artifacts is None else artifacts,
    )
    result = verify_github_progress_source(
        intent,
        transport=transport,
        read_artifact_zip=lambda art_id: (
            standard_archive if archive is None else archive
        ) if art_id == ARTIFACT_ID else None,
        expected_repository=REPO,
        trusted_workflows=frozenset({WORKFLOW}),
        trusted_actor="HyungseonSong-plasma",
        approved_main_sha=HEAD,
    )
    return result, transport


class SingleWriterLiveTests(unittest.TestCase):
    def test_complete_run_and_authenticated_zip_attest_full_receipt(self):
        intent, *_ = fixture()
        proof, transport = verified(intent)
        self.assertEqual(proof["unit_id"], intent["unit_id"])
        self.assertEqual(proof["detail_sha256"], intent["detail_sha256"])
        self.assertEqual(len(transport.calls), 2)
        self.assertIn("artifacts", transport.calls[-1][0])

    def test_absent_or_false_source_success_is_denied(self):
        for change in (
            {"conclusion": "failure"},
            {"status": "in_progress"},
            {"head_sha": "b" * 40},
            {"event": "pull_request"},
            {"head_branch": "feature"},
            {"run_attempt": 2},
            {"actor": {"login": "external"}},
            {"path": ".github/workflows/ci.yml@refs/heads/main"},
            {"repository": {"full_name": "other/repo"}},
        ):
            with self.subTest(change=change):
                _, run, _, _, _ = fixture()
                run.update(change)
                with self.assertRaisesRegex(LiveEvidenceError, "origin or terminal"):
                    verified(run=run)

    def test_exact_source_identity_policy_is_required(self):
        intent, _, _, _, _ = fixture()
        intent["source"]["workflow"] = "samuel-evidence-acquisition.yml"
        with self.assertRaisesRegex(Exception, "request id"):
            verified(intent)
        with self.assertRaisesRegex(LiveEvidenceError, "unapproved source commit"):
            verify_github_progress_source(
                fixture()[0],
                transport=GithubTransport(),
                read_artifact_zip=lambda _: b"",
                expected_repository=REPO,
                trusted_workflows=frozenset({WORKFLOW}),
                trusted_actor="HyungseonSong-plasma",
                approved_main_sha="b" * 40,
            )

    def test_zip_tampering_extra_members_and_expiry_denied(self):
        intent, run, artifact, archive, manifest = fixture()
        cases = [
            (archive[:-10], artifact),
            (archive_bytes(manifest, extra=True), artifact),
            (b"not a zip", artifact),
        ]
        for payload, meta in cases:
            with self.subTest(length=len(payload)):
                with self.assertRaises(LiveEvidenceError):
                    verified(intent, run=run, artifacts=meta, archive=payload)
        expired = copy.deepcopy(artifact)
        expired["artifacts"][0]["expired"] = True
        with self.assertRaisesRegex(LiveEvidenceError, "identity or expiry"):
            verified(intent, artifacts=expired)

    def test_duplicate_artifacts_or_mismatched_github_checksum_denied(self):
        _, _, artifact, _, _ = fixture()
        multi = copy.deepcopy(artifact)
        multi["total_count"] = 2
        with self.assertRaisesRegex(LiveEvidenceError, "exactly one"):
            verified(artifacts=multi)
        wrong = copy.deepcopy(artifact)
        wrong["artifacts"][0]["digest"] = "sha256:" + "f" * 64
        with self.assertRaisesRegex(LiveEvidenceError, "GitHub artifact digest"):
            verified(artifacts=wrong)

    def test_manifest_must_equal_intent_even_with_matching_archive_hash(self):
        intent, run, artifact, _, manifest = fixture()
        corrupt = copy.deepcopy(manifest)
        corrupt["unit_id"] = "docs/another.md"
        altered = archive_bytes(corrupt)
        intent["source"]["artifact_sha256"] = sha(altered)
        intent["request_id"] = hashlib.sha256(json.dumps(
            {k: v for k, v in intent.items() if k != "request_id"},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode()).hexdigest()
        artifact["artifacts"][0]["digest"] = "sha256:" + sha(altered)
        with self.assertRaisesRegex(LiveEvidenceError, "manifest result identity"):
            verified(intent, artifacts=artifact, archive=altered)

    def test_two_complete_pages_then_one_short_page(self):
        comments = [
            {"id": i + 1, "body": f"comment{i}",
             "user": {"login": "github-actions[bot]"}}
            for i in range(201)
        ]
        transport = GithubTransport(comments=comments)
        result = read_stable_issue_comments(transport, issue_number=44)
        self.assertEqual(len(result), 201)
        self.assertEqual(len(transport.calls), 6)
        self.assertEqual(transport.calls[0][1]["page"], "1")
        self.assertEqual(transport.calls[-1][1]["page"], "3")

    def test_unstable_read_or_bad_page_stops(self):
        comments = [
            {"id": i + 1, "body": f"body{i}",
             "user": {"login": "github-actions[bot]"}}
            for i in range(11)
        ]
        unstable = GithubTransport(comments=comments)
        unstable.unstable = True
        with self.assertRaisesRegex(LiveEvidenceError, "changed during"):
            read_stable_issue_comments(unstable, issue_number=44)
        duplicate = GithubTransport(comments=comments)
        duplicate.comments[1]["id"] = 1
        with self.assertRaisesRegex(LiveEvidenceError, "duplicate ID"):
            read_stable_issue_comments(duplicate, issue_number=44)

    def test_unbounded_comment_history_is_not_partially_processed(self):
        history = [
            {"id": index + 1, "body": "historical comment",
             "user": {"login": "github-actions[bot]"}}
            for index in range(2001)
        ]
        with self.assertRaisesRegex(LiveEvidenceError, "exceeds safety bound"):
            read_stable_issue_comments(
                GithubTransport(comments=history), issue_number=44,
            )

    def test_full_inbox_to_trusted_zip_to_read_only_write_plan(self):
        intent, run, artifacts, archive, _ = fixture()
        cp = create_checkpoint(
            work_id=intent["work_id"],
            plan_sha256=intent["plan_sha256"],
            policy_sha256=intent["policy_sha256"],
            units=[{"id": intent["unit_id"], "input_sha256": intent["input_sha256"],
                    "requires": [], "gates": ["source_current"]}],
        )
        state = attach_checkpoint(
            ResearchState(intent["work_id"], "fully attested pilot"), cp
        )
        intent = create_intent(
            work_id=state.research_id, base_revision=state.revision,
            plan_sha256=intent["plan_sha256"],
            policy_sha256=intent["policy_sha256"],
            unit_id=intent["unit_id"], input_sha256=intent["input_sha256"],
            outcome="PASS", detail=intent["detail"], source=intent["source"],
        )
        transport = GithubTransport(run, artifacts, [
            {"id": 44, "body": encode_state(state), "user": {"login": "github-actions[bot]"}},
            {"id": 101, "body": encode_inbox_comment(intent),
             "user": {"login": "github-actions[bot]"}},
        ])
        result = qualify_next_inbox_request(
            transport, issue_number=44,
            read_artifact_zip=lambda artifact_id: archive,
            trusted_comment_authors=frozenset({"github-actions[bot]"}),
            trusted_actor="HyungseonSong-plasma",
            expected_repository=REPO,
            trusted_workflows=frozenset({WORKFLOW}),
            approved_main_sha=HEAD,
            live_gate_states={"source_current": "PASS"},
        )
        self.assertEqual(result["status"], "WRITE_PROPOSAL")
        self.assertEqual(result["request_id"], intent["request_id"])
        self.assertEqual(result["state_write"]["expected_revision"], state.revision + 1)
        self.assertNotIn("PATCH", [p for p, _ in transport.calls])
        run["conclusion"] = "failure"
        transport.run = run
        with self.assertRaisesRegex(LiveEvidenceError, "origin or terminal"):
            qualify_next_inbox_request(
                transport, issue_number=44,
                read_artifact_zip=lambda artifact_id: archive,
                trusted_comment_authors=frozenset({"github-actions[bot]"}),
                trusted_actor="HyungseonSong-plasma",
                expected_repository=REPO,
                trusted_workflows=frozenset({WORKFLOW}),
                approved_main_sha=HEAD,
                live_gate_states={"source_current": "PASS"},
            )

    def test_verified_source_integrates_with_existing_state_write_planner(self):
        intent, _, _, _, _ = fixture()
        cp = create_checkpoint(
            work_id=intent["work_id"],
            plan_sha256=intent["plan_sha256"],
            policy_sha256=intent["policy_sha256"],
            units=[{"id": intent["unit_id"], "input_sha256": intent["input_sha256"],
                    "requires": [], "gates": ["source_current"]}],
        )
        state = attach_checkpoint(
            ResearchState(intent["work_id"], "read-only verified source"), cp
        )
        intent = create_intent(
            work_id=intent["work_id"], base_revision=state.revision,
            plan_sha256=intent["plan_sha256"],
            policy_sha256=intent["policy_sha256"], unit_id=intent["unit_id"],
            input_sha256=intent["input_sha256"], outcome=intent["outcome"],
            detail=intent["detail"], source=intent["source"],
        )
        comments = [{"id": 44, "body": encode_state(state)}]
        proposal = plan_progress_write(
            comments, intent,
            verify_source=lambda _: verified(intent)[0],
            allowed_repository=REPO,
            allowed_workflows=frozenset({WORKFLOW}),
            live_gate_states={"source_current": "PASS"},
        )
        self.assertEqual(proposal["status"], "WRITE_PROPOSAL")
        self.assertEqual(proposal["state_write"]["expected_previous_revision"], state.revision)


if __name__ == "__main__":
    unittest.main()
