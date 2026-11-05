"""Adversarial tests for read-only David Arena Pipeline replay."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from chatgpt_operation.controller.dea_v01_replay import ReplayError, _direct_sites, replay


class DeanV01ReplayTests(unittest.TestCase):
    def test_import_sites_are_ast_not_comments_or_strings(self):
        source = b'"""import subprocess"""\n# import subprocess\nimport subprocess as sp\nfrom subprocess import run\n'
        self.assertEqual(_direct_sites(source, "x.py"), [3, 4])

    def test_malformed_source_is_not_false_pass(self):
        with self.assertRaises(ReplayError):
            _direct_sites(b"def broken(", "bad.py")

    def test_exact_git_replay_and_non_authorizing_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args: str) -> str:
                return subprocess.check_output(
                    ["git", *args], cwd=root, stderr=subprocess.DEVNULL
                ).decode("ascii").strip()
            git("init", "-q")
            git("config", "user.name", "DEA Test")
            git("config", "user.email", "dea@example.invalid")
            folder = root / "src/codeqa/pipeline"
            folder.mkdir(parents=True)
            (folder / "one.py").write_text("import subprocess\n")
            (folder / "two.py").write_text("from subprocess import run\n")
            git("add", ".")
            git("commit", "-qm", "baseline")
            before = git("rev-parse", "HEAD")
            (folder / "one.py").write_text("from codeqa.infrastructure.git import GitReader\n")
            (folder / "two.py").write_text("from codeqa.infrastructure.git import GitReader\n")
            git("add", ".")
            git("commit", "-qm", "cleanup")
            after = git("rev-parse", "HEAD")

            result = replay(root, before=before, after=after)
            self.assertEqual(result["selected_python_files"], 2)
            self.assertEqual(result["site_delta"], -2)
            self.assertEqual(result["direct_subprocess_import_sites_after"], 0)
            self.assertEqual(result["decision"], "EVIDENCE_ONLY")
            self.assertEqual(result["semantic_compatibility"], "NOT_EVALUATED")
            self.assertIsNone(result["champion"])
            self.assertFalse(result["repository_mutation_authorized"])
            self.assertEqual(json.loads(json.dumps(result)), result)
            with self.assertRaises(ReplayError):
                replay(root, before=after, after=before)
            with self.assertRaises(ReplayError):
                replay(root, before="not-a-sha", after=after)

    def test_changed_source_selection_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args: str) -> str:
                return subprocess.check_output(
                    ["git", *args], cwd=root, stderr=subprocess.DEVNULL
                ).decode("ascii").strip()
            git("init", "-q")
            git("config", "user.name", "DEA Test")
            git("config", "user.email", "dea@example.invalid")
            folder = root / "src/codeqa/pipeline"
            folder.mkdir(parents=True)
            (folder / "one.py").write_text("import subprocess\n")
            git("add", ".")
            git("commit", "-qm", "baseline")
            before = git("rev-parse", "HEAD")
            (folder / "other.py").write_text("pass\n")
            git("add", ".")
            git("commit", "-qm", "change denominator")
            after = git("rev-parse", "HEAD")
            with self.assertRaisesRegex(ReplayError, "changed denominator"):
                replay(root, before=before, after=after)


if __name__ == "__main__":
    unittest.main()
