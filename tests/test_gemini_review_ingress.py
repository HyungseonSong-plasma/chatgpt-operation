"""Credential-free adversarial gates for Samuel's owner-labeled review queue."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import tempfile
from pathlib import Path
import unittest

from chatgpt_operation.controller.gemini_review_ingress import (
    HOST_REPOSITORY, SOURCE_REPOSITORY, TRIGGER_LABEL,
    ReviewError, issue_identity, prepare_verified_review, main,
)
from chatgpt_operation.controller.gemini_review_adapter import canonical_bytes

BASE = "b" * 40
HEAD = "a" * 40
DIFF = (
    "diff --git a/docs/a.md b/docs/a.md\n"
    "--- a/docs/a.md\n+++ b/docs/a.md\n"
    "@@ -1 +1 @@\n-old\n+new\n"
)


def fixtures():
    packet = {
        "schema_version": 1, "repository": SOURCE_REPOSITORY,
        "base_sha": BASE, "head_sha": HEAD, "diff": DIFF,
        "diff_sha256": hashlib.sha256(DIFF.encode()).hexdigest(),
        "changed_paths": ["docs/a.md"],
        "criteria": ["Check that prior document authority has not changed."],
    }
    body = json.dumps({
        "schema_version": 1, "request_type": "SAMUEL_GEMINI_REVIEW",
        "pr_number": 300, "packet": packet,
    })
    event = {
        "repository": {"full_name": HOST_REPOSITORY},
        "action": "labeled",
        "label": {"name": TRIGGER_LABEL},
        "sender": {"login": "HyungseonSong-plasma"},
        "issue": {
            "number": 308, "title": "[Gemini Review] codeQA PR #300",
            "state": "open", "user": {"login": "HyungseonSong-plasma"},
            "labels": [{"name": TRIGGER_LABEL}], "body": body,
        },
    }
    pr = {
        "number": 300, "state": "open", "changed_files": 1,
        "base": {"ref": "main", "sha": BASE, "repo": {"full_name": SOURCE_REPOSITORY}},
        "head": {"sha": HEAD, "repo": {"full_name": SOURCE_REPOSITORY}},
    }
    files = [{"filename": "docs/a.md"}]
    return event, pr, DIFF, files


class GeminiIngressTests(unittest.TestCase):
    def test_exact_evidence_preflight_returns_request_hash_without_authority(self):
        event, pr, diff, files = fixtures()
        r = prepare_verified_review(event, pr, diff, files)
        self.assertEqual(r["status"], "VERIFIED_REVIEW_REQUEST")
        self.assertEqual(r["issue_number"], 308)
        self.assertEqual(r["packet"]["head_sha"], HEAD)
        self.assertEqual(r["source_pr_number"], 300)
        self.assertEqual(r["request_sha256"],
                         hashlib.sha256(canonical_bytes(r["packet"])).hexdigest())
        self.assertFalse(r["authority"]["merge_authorized"])
        self.assertFalse(r["authority"]["gemini_github_access"])

    def test_issue_only_route_is_not_dispatch_authority(self):
        e, _, _, _ = fixtures()
        identity = issue_identity(e)
        self.assertEqual(identity["source_repository"], SOURCE_REPOSITORY)
        self.assertEqual(identity["source_pr_number"], 300)
        self.assertNotIn("gemini_key", str(identity))

    def test_issue_gates_all_fail_closed(self):
        for mutate in (
            lambda x: x.update({"action": "opened"}),
            lambda x: x["label"].update({"name": "other-label"}),
            lambda x: x["sender"].update({"login": "attacker"}),
            lambda x: x["issue"]["user"].update({"login": "attacker"}),
            lambda x: x["issue"].update({"state": "closed"}),
            lambda x: x["issue"].update({"title": "casual issue"}),
            lambda x: x["issue"].update({"labels": []}),
            lambda x: x["issue"].update({"pull_request": {}}),
            lambda x: x["repository"].update({"full_name": "owner/other"}),
            lambda x: x["issue"].update({"body": "not json"}),
            lambda x: x["issue"].update({"body": "x" * 53_000}),
            lambda x: x["issue"].update({"number": True}),
        ):
            e, _, _, _ = fixtures()
            mutate(e)
            with self.subTest(e=e.get("action"), body=e["issue"].get("body", "")[:20]):
                with self.assertRaises(ReviewError):
                    issue_identity(e)

    def test_request_contract_and_repository_allowlist(self):
        def changed(mutator):
            e, _, _, _ = fixtures()
            req = json.loads(e["issue"]["body"])
            mutator(req)
            e["issue"]["body"] = json.dumps(req)
            return e
        variants = [
            lambda x: x.update({"request_type": "POST_TO_GITHUB"}),
            lambda x: x.update({"pr_number": 0}),
            lambda x: x.update({"schema_version": True}),
            lambda x: x["packet"].update({"repository": "attacker/other"}),
            lambda x: x["packet"].update({"head_sha": BASE}),
            lambda x: x["packet"].update({"diff_sha256": "0" * 64}),
        ]
        for mutator in variants:
            with self.subTest(mutator=mutator), self.assertRaises(ReviewError):
                issue_identity(changed(mutator))

    def test_stale_pr_and_source_identity_never_reach_gemini(self):
        for mutate in (
            lambda p: p["head"].update({"sha": "0" * 40}),
            lambda p: p["base"].update({"sha": "0" * 40}),
            lambda p: p["base"].update({"ref": "untrusted-branch"}),
            lambda p: p["head"]["repo"].update({"full_name": "another/repo"}),
            lambda p: p.update({"state": "closed"}),
            lambda p: p.update({"number": 301}),
            lambda p: p.update({"changed_files": 1000}),
        ):
            e, p, d, f = fixtures()
            mutate(p)
            with self.subTest(mutate=mutate), self.assertRaises(ReviewError):
                prepare_verified_review(e, p, d, f)

    def test_source_diff_and_file_inventory_must_match_live_pr(self):
        e, p, d, f = fixtures()
        for observed_diff, observed_files in (
            (d + "unexpected\n", f),
            (d[:-1], f),
            (d, []),
            (d, [{"filename": "docs/unseen.md"}]),
            (d, [{"filename": "docs/a.md"}, {"filename": "docs/a.md"}]),
        ):
            with self.subTest(diff_len=len(observed_diff), files=observed_files):
                with self.assertRaises(ReviewError):
                    prepare_verified_review(e, p, observed_diff, observed_files)
        self.assertEqual(prepare_verified_review(e, p, d, f)["status"],
                         "VERIFIED_REVIEW_REQUEST")

    def test_cli_identity_and_attested_packet(self):
        e, p, d, f = fixtures()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event_path = root / "event.json"
            event_path.write_text(json.dumps(e), encoding="utf-8")
            identity_path = root / "identity.json"
            self.assertEqual(main([
                "--event", str(event_path), "--output", str(identity_path),
                "--identify-only",
            ]), 0)
            identity = json.loads(identity_path.read_text())
            self.assertNotIn("packet", identity)
            (root / "meta.json").write_text(json.dumps(p))
            (root / "diff.patch").write_text(d)
            (root / "files.json").write_text(json.dumps(f))
            output_path = root / "prepared.json"
            self.assertEqual(main([
                "--event", str(event_path), "--output", str(output_path),
                "--pr-meta", str(root / "meta.json"),
                "--pr-diff", str(root / "diff.patch"),
                "--pr-files", str(root / "files.json"),
            ]), 0)
            result = json.loads(output_path.read_text())
            self.assertEqual(result["source_pr_number"], 300)
            self.assertIn("request_sha256", result)


if __name__ == "__main__":
    unittest.main()
