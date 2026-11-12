"""No authority escalation through a model output or stale review receipt."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import tempfile
from pathlib import Path
import unittest

from chatgpt_operation.controller.gemini_review_receipt import bind_review_receipt, main
from chatgpt_operation.controller.gemini_review_adapter import ReviewError, canonical_bytes


def fixtures():
    diff = (
        "diff --git a/docs/a.md b/docs/a.md\n"
        "--- a/docs/a.md\n+++ b/docs/a.md\n@@ -1 +1 @@\n-old\n+new\n"
    )
    packet = {
        "schema_version": 1, "repository": "HyungseonSong-plasma/codeQA",
        "base_sha": "b" * 40, "head_sha": "a" * 40,
        "diff": diff, "diff_sha256": hashlib.sha256(diff.encode()).hexdigest(),
        "changed_paths": ["docs/a.md"],
        "criteria": ["Confirm that a draft stays explicitly unapproved."],
    }
    request_sha = hashlib.sha256(canonical_bytes(packet)).hexdigest()
    prepared = {
        "status": "VERIFIED_REVIEW_REQUEST",
        "schema_version": 1,
        "issue_number": 309,
        "source_pr_number": 300,
        "request_sha256": request_sha,
        "packet": packet,
        "authority": {
            "merge_authorized": False, "mutation_authorized": False,
            "source_evidence": "EXACT_GITHUB_DIFF_AND_PR_METADATA",
        },
    }
    result = {
        "schema_version": 1, "status": "REVIEW_RETURNED",
        "provider": "gemini", "model": "gemini-2.5-flash", "backend": "api",
        "request_sha256": request_sha,
        "repository": packet["repository"],
        "base_sha": packet["base_sha"],
        "head_sha": packet["head_sha"],
        "diff_sha256": packet["diff_sha256"],
        "verdict": {
            "verdict": "PASS", "summary": "No issue within the supplied diff.",
            "findings": [],
        },
        "provenance": {"model_version": "gemini-2.5-flash", "tokens": {"totalTokenCount": 123}},
        "merge_authorized": False, "mutation_authorized": False,
        "semantic_acceptance": "REVIEW_REQUIRED",
    }
    return prepared, result


class ReceiptTests(unittest.TestCase):
    def test_good_receipt_is_bound_but_never_approves_merge(self):
        prepared, result = fixtures()
        receipt = bind_review_receipt(prepared, result)
        self.assertEqual(receipt["status"], "REVIEW_RECEIPT_BOUND")
        self.assertEqual(receipt["review_verdict"], "PASS")
        self.assertEqual(receipt["head_sha"], "a" * 40)
        self.assertEqual(receipt["human_adjudication"], "REQUIRED")
        self.assertFalse(receipt["merge_authorized"])
        self.assertFalse(receipt["mutation_authorized"])

    def test_replay_tampered_result_and_authority_never_pass(self):
        mutations = (
            ("head_sha", "0" * 40), ("base_sha", "0" * 40),
            ("diff_sha256", "0" * 64), ("request_sha256", "0" * 64),
            ("provider", "github-actions"),
            ("merge_authorized", True), ("mutation_authorized", True),
            ("semantic_acceptance", "PASS"),
        )
        for key, value in mutations:
            p, r = fixtures()
            r[key] = value
            with self.subTest(key=key), self.assertRaises(ReviewError):
                bind_review_receipt(p, r)
        p, r = fixtures()
        p["request_sha256"] = "0" * 64
        with self.assertRaises(ReviewError):
            bind_review_receipt(p, r)
        p, r = fixtures()
        p["status"] = "UNVERIFIED"
        with self.assertRaises(ReviewError):
            bind_review_receipt(p, r)

    def test_unknown_is_bound_to_issue_without_synthetic_success(self):
        p, _ = fixtures()
        r = {
            "schema_version": 1, "status": "UNKNOWN", "failure": "ReviewError",
            "merge_authorized": False, "mutation_authorized": False,
        }
        observed = bind_review_receipt(p, r)
        self.assertEqual(observed["status"], "UNKNOWN")
        self.assertEqual(observed["review_verdict"], "UNKNOWN")
        self.assertEqual(observed["source_pr_number"], 300)
        self.assertFalse(observed["merge_authorized"])
        r["merge_authorized"] = True
        with self.assertRaises(ReviewError):
            bind_review_receipt(p, r)

    def test_cli_writes_exact_receipt_and_rejects_unbound(self):
        p, r = fixtures()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a, b, c = (root / x for x in ("request.json", "result.json", "bound.json"))
            a.write_text(json.dumps(p))
            b.write_text(json.dumps(r))
            self.assertEqual(main([
                "--request", str(a), "--result", str(b), "--output", str(c),
            ]), 0)
            self.assertEqual(json.loads(c.read_text())["status"], "REVIEW_RECEIPT_BOUND")
            r["head_sha"] = "0" * 40
            b.write_text(json.dumps(r))
            self.assertEqual(main([
                "--request", str(a), "--result", str(b), "--output", str(c),
            ]), 2)


if __name__ == "__main__":
    unittest.main()
