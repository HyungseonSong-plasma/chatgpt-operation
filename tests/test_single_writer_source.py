"""Exact checked-out doc evidence producer and workflow policy tests."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from chatgpt_operation.controller.progress_resume import detail_digest
from chatgpt_operation.controller.single_writer_source import (
    SourceEvidenceError, make_readonly_document_manifest,
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def produce(root, raw, *, unit="docs/a.md", input_hash=None, attempt=1):
    return make_readonly_document_manifest(
        repository_root=root,
        unit_id=unit,
        input_sha256=input_hash or sha(raw),
        work_id="issue:qualification",
        plan_sha256=sha(b"plan"),
        policy_sha256=sha(b"policy"),
        head_sha="a" * 40,
        run_id=1234,
        run_attempt=attempt,
    )


class SingleWriterSourceTests(unittest.TestCase):
    def test_exact_document_snapshot_generates_lossless_deterministic_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/"docs").mkdir()
            raw=b"# example\n[one](../README.md)\n[two](../test.md)\n"
            (root/"docs/a.md").write_bytes(raw)
            result=produce(root,raw)
            self.assertEqual(result["input_sha256"],sha(raw))
            self.assertEqual(result["detail_sha256"],detail_digest(result["detail"]))
            self.assertEqual(result["detail"]["line_count"],3)
            self.assertEqual(
                [x["target"] for x in result["detail"]["markdown_link_occurrences"]],
                ["../README.md","../test.md"],
            )
            self.assertEqual(produce(root,raw),result)

    def test_mismatched_input_or_unsafe_target_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/"docs").mkdir()
            raw=b"plain\n"
            (root/"docs/a.md").write_bytes(raw)
            with self.assertRaisesRegex(SourceEvidenceError,"SHA differs"):
                produce(root,raw,input_hash="f"*64)
            with self.assertRaisesRegex(SourceEvidenceError,"outside bounded"):
                produce(root,raw,unit="docs/../../secrets.md")
            with self.assertRaisesRegex(SourceEvidenceError,"outside bounded"):
                produce(root,raw,unit="src/controller.py")
            (root/"docs/link.md").symlink_to(root/"docs/a.md")
            with self.assertRaisesRegex(SourceEvidenceError,"symlinked"):
                produce(root,raw,unit="docs/link.md")
            with self.assertRaisesRegex(SourceEvidenceError,"run identity"):
                produce(root,raw,attempt=2)

    def test_workflow_is_read_only_and_main_actor_pinned(self):
        workflow=Path(".github/workflows/samuel-progress-evidence.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("contents: read",workflow)
        self.assertIn("actions: read",workflow)
        self.assertNotIn("issues: write",workflow)
        self.assertNotIn("pull-requests: write",workflow)
        self.assertIn("github.ref == 'refs/heads/main'",workflow)
        self.assertIn("github.actor == 'HyungseonSong-plasma'",workflow)
        self.assertIn("name: samuel-progress-evidence-",workflow)
        self.assertIn("--output progress-evidence.json",workflow)
        self.assertNotIn("gh api --method PATCH",workflow)
        self.assertNotIn("gh api --method POST",workflow)


if __name__ == "__main__":
    unittest.main()
