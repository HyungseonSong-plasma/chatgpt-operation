"""Adversarial and real immutable codeQA preview tests for the DEA oracle."""
from __future__ import annotations

import copy
from pathlib import Path
import subprocess
import tempfile
import unittest
import os

from chatgpt_operation.controller.dea_reference_oracle import (
    ReferenceOracleError, compare_candidate, compare_transition, observe_sources, scan_git_snapshot, verify_candidate_from_git,
)

PIN = "da14ec9bd6bdbea2b535bd91331b88ecce698413"


def golden_corpus():
    return {
        "docs/index.md": (
            "# Contents\n"
            "[Go](guide.md#usage)\n"
            "[Alias][g]\n"
            "[g]: guide.md#usage\n"
            '<a href="guide.md#usage">Jump</a>\n'
            "&#10; ignored\n"
            "\x60[inline_code](absent.md)\x60\n"
            "~~~python\n[ignored](absent.md)\n~~~\n"
            "[Missing](not-found.md)\n"
            "[External](https://example.com/help)\n"
        ).encode(),
        "docs/guide.md": b"# Usage\n## Usage\n## Usage\n",
        "src/refs.py": b"source='docs/guide.md'\n# docs/missing.md\n",
    }


class ReferenceOracleFixtureTests(unittest.TestCase):
    def test_hand_curated_golden_cases(self):
        result = observe_sources(golden_corpus(), revision="a" * 40)
        self.assertEqual(result["selected_file_count"], 3)
        self.assertEqual(result["origin"], "CALLER_SUPPLIED_UNATTESTED")
        self.assertEqual(result["unsupported_syntax_count"], 0)
        self.assertEqual(result["status_counts"], {
            "EXTERNAL_NOT_EVALUATED": 1,
            "LITERAL_EXISTS_UNCLASSIFIED": 1,
            "LITERAL_MISSING_UNCLASSIFIED": 1,
            "LOCAL_RESOLVED": 4,
            "MISSING_LOCAL_TARGET": 1,
        })
        rows = result["records"]
        self.assertEqual(len(rows), 8)
        self.assertFalse(any(row["raw_target"] == "absent.md" for row in rows))
        self.assertTrue(any(row["kind"] == "markdown_reference"
                            and row["line"] == 3 for row in rows))

    def test_fail_closed_on_changed_reference_or_wrong_source(self):
        result = observe_sources(golden_corpus(), revision="a" * 40)
        invalid = dict(golden_corpus())
        invalid["docs/index.md"] += b"\n[Other](missing2.md)\n"
        changed = observe_sources(invalid, revision="a" * 40)
        self.assertNotEqual(result["corpus_digest_sha256"],
                            changed["corpus_digest_sha256"])
        with self.assertRaises(ReferenceOracleError):
            observe_sources(invalid, revision="not-a-commit")
        with self.assertRaises(ReferenceOracleError):
            observe_sources({"../escape.md": b"hi"}, revision="a" * 40)

    def test_uncertain_syntax_remains_unknown_not_pass(self):
        files = {"docs/x.md": b"# Top\n[Bad][missing]\n[Odd](nested(x).md)\n"}
        result = observe_sources(files, revision="b" * 40)
        self.assertTrue(any(x["status"] == "UNSUPPORTED_REFERENCE"
                            for x in result["records"]))
        self.assertGreater(result["unsupported_syntax_count"], 0)

    def test_nested_markdown_link_is_explicitly_not_evaluated(self):
        report = observe_sources(
            {"docs/x.md": b"[Complex](nested(name).md)\n"},
            revision="c" * 40,
        )
        self.assertIn("UNSUPPORTED_MARKDOWN_SYNTAX",
                      report["status_counts"])
        self.assertGreater(report["unsupported_syntax_count"], 0)

    def test_untrusted_caller_cannot_claim_trusted_attestation(self):
        candidate = observe_sources(golden_corpus(), revision="a" * 40)
        with self.assertRaisesRegex(ReferenceOracleError, "trusted"):
            compare_candidate(candidate, copy.deepcopy(candidate))


class ReferenceOracleGitTests(unittest.TestCase):
    def test_exact_git_readback_and_candidate_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            def git(*args):
                return subprocess.check_output(
                    ["git", *args], cwd=root, stderr=subprocess.DEVNULL,
                ).decode().strip()

            git("init", "-q")
            git("config", "user.name", "DEA Oracle")
            git("config", "user.email", "dea-oracle@example.invalid")
            for path, contents in golden_corpus().items():
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(contents)
            git("add", ".")
            git("commit", "-qm", "fixture")
            head = git("rev-parse", "HEAD")
            before = git("status", "--porcelain")
            report = scan_git_snapshot(root, head)
            self.assertEqual(report["origin"], "EXACT_GIT_OBJECT_READBACK")
            self.assertEqual(report["selected_file_count"], 3)
            self.assertEqual(report["source_revision"], head)
            self.assertEqual(before, git("status", "--porcelain"))
            submission = copy.deepcopy(report)
            self.assertEqual(compare_candidate(report, submission)["status"],
                             "PASS_BOUNDED")
            submission["records"].pop()
            self.assertEqual(compare_candidate(report, submission)["status"],
                             "FAIL")
            submission = copy.deepcopy(report)
            submission["corpus_digest_sha256"] = "0" * 64
            with self.assertRaises(ReferenceOracleError):
                compare_candidate(report, submission)

    def test_incremental_transition_cannot_mask_stale_index(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            def git(*args):
                return subprocess.check_output(
                    ["git", *args], cwd=root, stderr=subprocess.DEVNULL,
                ).decode().strip()

            git("init", "-q")
            git("config", "user.name", "DEA Oracle")
            git("config", "user.email", "dea-oracle@example.invalid")
            for path, data in golden_corpus().items():
                destination = root / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
            git("add", ".")
            git("commit", "-qm", "before")
            old_sha = git("rev-parse", "HEAD")
            old = scan_git_snapshot(root, old_sha)
            index = root / "docs/index.md"
            index.write_bytes(index.read_bytes().replace(
                b"[Missing](not-found.md)", b"[Fixed](guide.md#usage)"
            ))
            git("add", ".")
            git("commit", "-qm", "after")
            new_sha = git("rev-parse", "HEAD")
            new = scan_git_snapshot(root, new_sha)
            actual = {"docs/index.md"}
            result = compare_transition(
                old, new, copy.deepcopy(old), copy.deepcopy(new),
                claimed_changed_selected_paths=actual,
            )
            self.assertEqual(result["status"], "PASS_BOUNDED")
            # A stale incremental cache cannot reuse prior source identity.
            with self.assertRaises(ReferenceOracleError):
                compare_transition(
                    old, new, copy.deepcopy(old), copy.deepcopy(old),
                    claimed_changed_selected_paths=actual,
                )
            with self.assertRaises(ReferenceOracleError):
                compare_transition(
                    old, new, copy.deepcopy(old), copy.deepcopy(new),
                    claimed_changed_selected_paths=set(),
                )

    def test_verified_candidate_uses_fresh_git_not_forged_origin(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            def git(*args):
                return subprocess.check_output(
                    ["git", *args], cwd=root, stderr=subprocess.DEVNULL,
                ).decode().strip()

            git("init", "-q")
            git("config", "user.name", "DEA Oracle")
            git("config", "user.email", "dea-oracle@example.invalid")
            (root / "docs").mkdir()
            (root / "docs/index.md").write_text(
                "# Home\n[Good](guide.md)\n", encoding="utf-8"
            )
            (root / "docs/guide.md").write_text("# Guide\n", encoding="utf-8")
            git("add", ".")
            git("commit", "-qm", "trusted fixture")
            sha = git("rev-parse", "HEAD")
            trusted = scan_git_snapshot(root, sha)
            candidate = copy.deepcopy(trusted)
            candidate["origin"] = "EXACT_GIT_OBJECT_READBACK"
            good = verify_candidate_from_git(root, sha, candidate)
            self.assertEqual(good["status"], "PASS_BOUNDED")
            self.assertEqual(good["candidate_artifact_origin"], "NOT_ATTESTED")
            self.assertEqual(good["ci_runner_integrity"], "NOT_ATTESTED")
            candidate["records"] = []
            self.assertEqual(
                verify_candidate_from_git(root, sha, candidate)["status"], "FAIL"
            )
            candidate = copy.deepcopy(trusted)
            candidate["source_revision"] = "f" * 40
            with self.assertRaises(ReferenceOracleError):
                verify_candidate_from_git(root, sha, candidate)
            with self.assertRaises(ReferenceOracleError):
                verify_candidate_from_git(root, "f" * 40, trusted)
            with self.assertRaises(ReferenceOracleError):
                verify_candidate_from_git(root, sha, None)

    def test_untracked_or_unknown_commit_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            with self.assertRaises(ReferenceOracleError):
                scan_git_snapshot(root, "f" * 40)

    def test_missing_fragment_is_not_falsely_passed(self):
        files = {
            "docs/a.md": b"[Nope](b.md#unknown)\n",
            "docs/b.md": b"# Existing\n",
        }
        result = observe_sources(files, revision="c" * 40)
        self.assertEqual(result["status_counts"], {"FRAGMENT_NOT_EVALUATED": 1})
        self.assertEqual(result["unsupported_syntax_count"], 1)


@unittest.skipUnless(os.environ.get("GITHUB_ACTIONS") == "true",
                     "requires pinned remote source fetch on trusted CI")
class ActualCodeQAPreviewTests(unittest.TestCase):
    def test_preview_pr289_head_without_mutating_codeqa(self):
        with tempfile.TemporaryDirectory(prefix="dea-doc-oracle-") as td:
            root = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True,
                           stdout=subprocess.DEVNULL)
            subprocess.run(
                ["git", "remote", "add", "origin",
                 "https://github.com/HyungseonSong-plasma/codeQA.git"],
                cwd=root, check=True, stdout=subprocess.DEVNULL,
            )
            result = subprocess.run(["git", "fetch", "--no-tags", "--depth=1",
                                     "origin", PIN], cwd=root,
                                    capture_output=True, timeout=120, check=False)
            self.assertEqual(result.returncode, 0, result.stderr.decode()[-1500:])
            report = scan_git_snapshot(root, PIN)
            self.assertEqual(report["source_revision"], PIN)
            self.assertEqual(report["origin"], "EXACT_GIT_OBJECT_READBACK")
            self.assertGreater(report["tracked_path_count"], 300)
            self.assertGreater(report["selected_file_count"], 100)
            self.assertGreater(len(report["records"]), 100)
            self.assertEqual(report["repository_mutation_authorized"], False)
            self.assertEqual(report["completeness"],
                             "BOUNDED_SUBSET_NOT_FULL_MARKDOWN")
            self.assertEqual(report["external_consumer_coverage"],
                             "NOT_EVALUATED")


if __name__ == "__main__":
    unittest.main()
