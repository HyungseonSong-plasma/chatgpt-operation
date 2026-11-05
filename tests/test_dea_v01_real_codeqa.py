"""CI-only independent read-only Git-object replay of the real codeQA cleanup."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from chatgpt_operation.controller.dea_v01_replay import replay

BEFORE = "fb54b6c92363476b07a726008fbe8c1ab35f1a6a"
AFTER = "6aa15e8613b95bf39233a7b191a730f257d7adb3"
PUBLIC_REPO = "https://github.com/HyungseonSong-plasma/codeQA.git"


@unittest.skipUnless(os.environ.get("GITHUB_ACTIONS") == "true",
                     "networked Git historical replay is CI-only")
class ActualCodeQAReplay(unittest.TestCase):
    def test_pinned_historical_12_file_replay(self):
        with tempfile.TemporaryDirectory(prefix="dea-codeqa-readonly-") as td:
            root = Path(td)

            def git(*args: str) -> str:
                p = subprocess.run(["git", *args], cwd=root, capture_output=True,
                                   text=True, check=False, timeout=100)
                self.assertEqual(p.returncode, 0, p.stderr[-1500:])
                return p.stdout.strip()

            git("init", "-q")
            git("remote", "add", "origin", PUBLIC_REPO)
            # This commit includes the immutable before version in its ancestry.
            # Fetch a bounded history; do not checkout/execute codeQA code.
            git("fetch", "--no-tags", "--depth=128", "origin", AFTER)
            result = replay(root, before=BEFORE, after=AFTER)
            self.assertEqual(result["selected_python_files"], 12)
            self.assertEqual(result["direct_subprocess_import_sites_before"], 2)
            self.assertEqual(result["direct_subprocess_import_sites_after"], 0)
            self.assertEqual(result["site_delta"], -2)
            self.assertEqual(result["decision"], "EVIDENCE_ONLY")
            self.assertEqual(result["semantic_compatibility"], "NOT_EVALUATED")
            self.assertFalse(result["repository_mutation_authorized"])


if __name__ == "__main__":
    unittest.main()
