from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from chatgpt_operation.work.matrix import MatrixError, extract_bundle, load_matrix_manifest, self_test


class GovernedMatrixTests(unittest.TestCase):
    def test_self_test(self):
        self.assertEqual(self_test(), 0)

    def test_rejects_overlapping_bundle_paths(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "matrix.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "issue": 1,
                        "sequence": 1,
                        "title": "bad",
                        "prepare_manifest": "automation/manifests/experiments/prep.json",
                        "bundle_paths": ["build", "build/app"],
                        "cases": [
                            {"id": "a", "name": "a", "command": ["python3", "-V"]}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(MatrixError):
                load_matrix_manifest(path)

    def test_rejects_glob_bundle_path(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "matrix.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "issue": 1,
                        "sequence": 1,
                        "title": "bad",
                        "prepare_manifest": "automation/manifests/experiments/prep.json",
                        "bundle_paths": ["build/*"],
                        "cases": [
                            {"id": "a", "name": "a", "command": ["python3", "-V"]}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(MatrixError):
                load_matrix_manifest(path)


if __name__ == "__main__":
    unittest.main()
