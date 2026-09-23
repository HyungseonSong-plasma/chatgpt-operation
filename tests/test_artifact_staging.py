from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from chatgpt_operation.artifact_staging import StagingError, load_spec, self_test, stage


class ArtifactStagingTests(unittest.TestCase):
    def test_self_test(self):
        self.assertEqual(self_test(), 0)

    def test_rejects_glob_source(self):
        with tempfile.TemporaryDirectory() as td:
            spec = Path(td) / "spec.json"
            spec.write_text(json.dumps({
                "schema_version": 1,
                "entries": [{
                    "id": "bad",
                    "source": "/tmp/lib*.so",
                    "destination": "runtime/lib.so",
                    "producer": "build",
                    "location_evidence": "observed build output",
                }],
            }), encoding="utf-8")
            with self.assertRaises(StagingError):
                load_spec(spec)

    def test_rejects_missing_location_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            spec = Path(td) / "spec.json"
            spec.write_text(json.dumps({
                "schema_version": 1,
                "entries": [{
                    "id": "bad",
                    "source": "/tmp/lib.so",
                    "destination": "runtime/lib.so",
                    "producer": "build",
                }],
            }), encoding="utf-8")
            with self.assertRaises(StagingError):
                load_spec(spec)

    def test_missing_exact_source_is_unresolved(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = root / "workspace"
            workspace.mkdir()
            spec = root / "spec.json"
            spec.write_text(json.dumps({
                "schema_version": 1,
                "entries": [{
                    "id": "missing",
                    "source": str(root / "does-not-exist.so"),
                    "destination": "runtime/lib.so",
                    "producer": "build",
                    "location_evidence": "expected exact path from build contract",
                }],
            }), encoding="utf-8")
            with self.assertRaisesRegex(StagingError, "ARTIFACT_LOCATION_UNRESOLVED"):
                stage(spec_path=spec, workspace=workspace)

    def test_materializes_exact_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = root / "workspace"
            workspace.mkdir()
            real = root / "libx.so.0"
            real.write_bytes(b"payload")
            link = root / "libx.so"
            link.symlink_to(real.name)
            spec = root / "spec.json"
            spec.write_text(json.dumps({
                "schema_version": 1,
                "entries": [{
                    "id": "libx",
                    "source": str(link),
                    "destination": "runtime/libx.so",
                    "producer": "build",
                    "location_evidence": "link path emitted by producer",
                    "symlink_policy": "materialize",
                }],
            }), encoding="utf-8")
            result = stage(spec_path=spec, workspace=workspace)
            staged = workspace / "runtime/libx.so"
            self.assertEqual(staged.read_bytes(), b"payload")
            self.assertFalse(staged.is_symlink())
            self.assertTrue(result["entries"][0]["symlink_materialized"])


if __name__ == "__main__":
    unittest.main()
