"""Fake-GitHub regression tests for the exact-head all-Core Gate 1 collector."""
from __future__ import annotations

import base64
import hashlib
import unittest

from chatgpt_operation.github.documentation_gate1_acquire_v01 import (
    collect_live_core_gate1_v01,
)
from chatgpt_operation.documentation.status_labels import LabelError

REPO = "HyungseonSong-plasma/codeQA"
HEAD = "a" * 40
TREE = "b" * 40
API = "repos/" + REPO
CORE = "src/codeqa/core/"


def hash_blob(data):
    return hashlib.sha1(
        b"blob " + str(len(data)).encode("ascii") + bytes([0]) + data
    ).hexdigest()


class FakeGitHub:
    def __init__(self):
        self.files = {
            "contracts/ccg/graph-v0.1.schema.json":
                '{"$id":"urn:codeqa:ccg:graph:v0.1"}',
            CORE + "__init__.py": "from .graph import Graph" + chr(10),
            CORE + "graph.py": "from dataclasses import dataclass" + chr(10),
            CORE + "nested/part.py": "from ..graph import Graph" + chr(10),
        }
        self.truncated = False
        self.unexpected_mode = None
        self.change_head_at_end = False
        self.read_count = 0
        self.return_malformed_blob = False

    def read(self, endpoint):
        self.read_count += 1
        if endpoint == API + "/pulls/289":
            calls = getattr(self, "pr_calls", 0) + 1
            self.pr_calls = calls
            sha = "c" * 40 if calls == 2 and self.change_head_at_end else HEAD
            return {"state": "open", "head": {
                "sha": sha, "repo": {"full_name": REPO}}}
        if endpoint == API + "/git/commits/" + HEAD:
            return {"sha": HEAD, "tree": {"sha": TREE}}
        if endpoint == API + "/git/trees/" + TREE + "?recursive=1":
            entries = []
            for path, value in self.files.items():
                blob_sha = hash_blob(value.encode("utf-8"))
                entries.append({
                    "path": path, "sha": blob_sha, "type": "blob",
                    "mode": self.unexpected_mode
                    if self.unexpected_mode and path.endswith("graph.py")
                    else "100644",
                })
            return {"sha": TREE, "truncated": self.truncated, "tree": entries}
        if endpoint.startswith(API + "/git/blobs/"):
            sha = endpoint.rsplit("/", 1)[1]
            for value in self.files.values():
                data = value.encode("utf-8")
                if hash_blob(data) == sha:
                    return {"sha": sha, "encoding": "base64",
                            "content": "not base64!"
                            if self.return_malformed_blob else
                            base64.b64encode(data).decode("ascii"),
                            "size": len(data)}
            raise AssertionError("unexpected blob: " + sha)
        raise AssertionError("unexpected endpoint: " + endpoint)

    def verify(self):
        return collect_live_core_gate1_v01(
            repository=REPO, pr_number=289, read_json=self.read,
            expected_head_sha=HEAD,
        )


class CoreLiveSourceAcquisitionTests(unittest.TestCase):
    def test_tree_enumerates_nested_core_files_and_checks_all(self):
        client = FakeGitHub()
        r = client.verify()
        self.assertEqual(r.git_tree_sha, TREE)
        self.assertEqual(len(r.core_python_files), 3)
        self.assertIn(CORE + "nested/part.py", r.core_python_files)
        self.assertEqual(set(r.gate1.check_results.values()), {"PASS"})
        self.assertEqual(len(r.gate1.check_results), 4)
        self.assertEqual(r.gate1.status, "SCOPED_CHECKS_PASS")
        self.assertEqual(r.independent_approval, "REVIEW_REQUIRED")
        self.assertEqual(r.semantic_certification, "NOT_EVALUATED")
        self.assertEqual(r.exact_head_sha, HEAD)
        self.assertEqual(getattr(client, "pr_calls", 0), 2)

    def test_detect_absolute_and_relative_adapters_imports(self):
        for import_stmt in (
            "import codeqa.adapters.python",
            "from codeqa import adapters",
            "from .. import adapters",
            "from ..adapters import python",
        ):
            with self.subTest(import_stmt=import_stmt):
                c = FakeGitHub()
                c.files[CORE + "graph.py"] = import_stmt + chr(10)
                r = c.verify()
                self.assertEqual(r.gate1.status, "REVIEW_REQUIRED")
                self.assertTrue(any("PREDICATE_FAILED" in x for x in r.gate1.issues))
                self.assertEqual(r.independent_approval, "REVIEW_REQUIRED")

    def test_new_nested_python_file_is_not_silently_skipped(self):
        c = FakeGitHub()
        c.files[CORE + "new/feature.py"] = "pass" + chr(10)
        r = c.verify()
        self.assertEqual(len(r.core_python_files), 4)
        self.assertIn(CORE + "new/feature.py", r.core_python_files)
        self.assertEqual(r.gate1.status, "SCOPED_CHECKS_PASS")

    def test_missing_init_or_schema_is_a_hard_failure(self):
        for missing in (CORE + "__init__.py",
                        "contracts/ccg/graph-v0.1.schema.json"):
            with self.subTest(missing=missing):
                c = FakeGitHub()
                del c.files[missing]
                with self.assertRaises(LabelError):
                    c.verify()

    def test_truncated_tree_fails_closed(self):
        c = FakeGitHub()
        c.truncated = True
        with self.assertRaises(LabelError):
            c.verify()

    def test_symlink_or_nonblob_fails_closed(self):
        c = FakeGitHub()
        c.unexpected_mode = "120000"
        with self.assertRaises(LabelError):
            c.verify()

    def test_head_drift_fails_closed(self):
        c = FakeGitHub()
        c.change_head_at_end = True
        with self.assertRaises(LabelError):
            c.verify()

    def test_invalid_blob_encoding_fails_closed(self):
        c = FakeGitHub()
        c.return_malformed_blob = True
        with self.assertRaises(LabelError):
            c.verify()

    def test_unresolved_relative_import_fails_closed(self):
        c = FakeGitHub()
        c.files[CORE + "graph.py"] = "from ... import adapters" + chr(10)
        r = c.verify()
        self.assertEqual(r.gate1.status, "REVIEW_REQUIRED")
        self.assertTrue(any("UNVERIFIABLE_PREDICATE" in x
                            for x in r.gate1.issues))


if __name__ == "__main__":
    unittest.main()
