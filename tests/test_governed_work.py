from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
import unittest

from chatgpt_operation.work.manifest import ManifestError, load_manifest
from chatgpt_operation.work.runner import self_test
from chatgpt_operation.work.scaffold import create_manifest


class GovernedWorkTests(unittest.TestCase):
    def test_runner_self_test(self):
        self.assertEqual(self_test(), 0)

    def test_scaffold_allocates_monotonic_identity(self):
        with tempfile.TemporaryDirectory() as td:
            first=create_manifest(
                issue=7,kind="experiments",title="one",root=td
            )
            second=create_manifest(
                issue=7,kind="experiments",title="two",root=td
            )
            self.assertEqual(first.name,"Issue_7_experiments01.json")
            self.assertEqual(second.name,"Issue_7_experiments02.json")

    def test_experiment_stage_prefix_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"bad.json"
            path.write_text(
                json.dumps({
                    "schema_version":1,
                    "issue":1,
                    "kind":"experiments",
                    "sequence":1,
                    "title":"bad",
                    "stages":[{
                        "id":"P1",
                        "name":"wrong first phase",
                        "command":["python3","-c","print('x')"]
                    }],
                    "artifacts":[]
                }),
                encoding="utf-8",
            )
            with self.assertRaises(ManifestError):
                load_manifest(path)

    def test_refactor_stage_is_not_physics_specific(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"ok.json"
            path.write_text(
                json.dumps({
                    "schema_version":1,
                    "issue":2,
                    "kind":"refactor",
                    "sequence":1,
                    "title":"refactor",
                    "stages":[{
                        "id":"VALIDATE",
                        "name":"validate",
                        "command":["python3","-c","print('ok')"]
                    }],
                    "artifacts":[]
                }),
                encoding="utf-8",
            )
            manifest=load_manifest(path)
            self.assertEqual(manifest.identity,"Issue_2_refactor01")


if __name__=="__main__":
    unittest.main()
