"""Guardrails for the draft human-controlled producer smoke Workflow.

This source lives in docs, not .github/workflows. Tests do not deploy it
and cannot amend repository policy.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
import textwrap
import unittest

BLUEPRINT = (
    Path(__file__).resolve().parents[1]
    / "docs/dea-v02-protected-producer-smoke.proposed.yml"
)


class ProducerSmokeBlueprintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = BLUEPRINT.read_text(encoding="utf-8")

    def test_draft_is_not_activated_and_nocandidate(self):
        self.assertIn("PROPOSED / NOT DEPLOYED", self.s)
        self.assertIn("workflow_dispatch:", self.s)
        self.assertNotIn("\n  pull_request:", self.s)
        self.assertNotIn("\n  pull_request_target:", self.s)
        self.assertNotIn("\n  push:", self.s)
        self.assertIn("SMOKE_ONLY_NOT_FITNESS", self.s)
        self.assertIn('"pareto_eligible": False', self.s)

    def test_human_environment_exact_main_and_expected_sha(self):
        self.assertIn("name: dea-human-break-glass", self.s)
        self.assertIn("refs/heads/main", self.s)
        self.assertIn("github.actor == 'HyungseonSong-plasma'", self.s)
        self.assertIn("EXPECTED_MAIN_SHA", self.s)
        self.assertIn('[[ "$EXPECTED_MAIN_SHA" == "$GITHUB_SHA" ]]', self.s)
        self.assertIn('[[ "$(git rev-parse HEAD)" == "$GITHUB_SHA" ]]', self.s)
        self.assertIn("persist-credentials: false", self.s)

    def test_actions_are_full_immutable_sha_pinned(self):
        actions = re.findall(r"^\s+uses:\s+(\S+)", self.s, re.MULTILINE)
        self.assertEqual(len(actions), 3)
        self.assertEqual(
            actions,
            [
                "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
                "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6",
                "actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9",
            ],
        )
        for a in actions:
            self.assertRegex(a, r"@[0-9a-f]{40}$")

    def test_signing_permissions_are_scoped_and_not_global(self):
        self.assertIn("permissions: {}", self.s)
        for p in ("contents: read", "id-token: write", "attestations: write"):
            self.assertIn(p, self.s)
        self.assertNotIn("contents: write", self.s)
        self.assertNotIn("workflow: write", self.s)
        self.assertNotIn("pull-requests: write", self.s)
        self.assertNotIn("cancel-in-progress: true", self.s)
        self.assertIn("create-storage-record: false", self.s)

    def test_attest_signed_inner_zip_before_upload(self):
        a = self.s.index("uses: actions/attest@")
        b = self.s.index("uses: actions/upload-artifact@")
        self.assertLess(a, b)
        self.assertIn("subject-path: dist/dea-evidence.zip", self.s)
        self.assertIn("path: dist/dea-evidence.zip", self.s)
        self.assertIn("if-no-files-found: error", self.s)
        self.assertIn("overwrite: false", self.s)
        self.assertIn("retention-days: 7", self.s)
        self.assertIn("sha256sum dist/dea-evidence.zip", self.s)
        self.assertIn("Artifact ID: $ARTIFACT_ID", self.s)

    def test_embedded_python_syntax_is_valid(self):
        marker = "          python3 - <<'PY'\n"
        self.assertEqual(self.s.count(marker), 1)
        code = self.s.split(marker, 1)[1].split("\n          PY", 1)[0]
        code = textwrap.dedent(code)
        ast.parse(code, filename="embedded_dea_smoke.py")
        self.assertIn("build_payload(", code)
        self.assertIn("inspect_payload(", code)
        self.assertNotIn("verify_sigstore_payload(", code)
        self.assertNotIn("github_attestation", code)

    def test_no_automatic_champion_or_fitness_pass(self):
        self.assertNotIn('"status": "PASS"', self.s)
        self.assertNotIn('"pareto_eligible": True', self.s)
        self.assertNotIn('"champion": True', self.s)
        self.assertIn("Fitness: UNKNOWN / not eligible", self.s)


if __name__ == "__main__":
    unittest.main()
