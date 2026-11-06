"""Pinned codeQA PR #289 source bytes exercise the actual Gate 1 checker."""
from __future__ import annotations

import copy
from contextlib import redirect_stdout
import io
import hashlib
import json
from pathlib import Path
import unittest

from chatgpt_operation.documentation.gate1_manifest_v01 import run_gate1_manifest_v01, main
from chatgpt_operation.documentation.status_labels import LabelError


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/document_consistency/codeqa_pr289"
MANIFEST = ROOT / "skills/document-consistency/codeqa-gate1-pilot-v0.1.json"


def witness():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    sources = {c["path"]: (FIXTURES / c["path"]).read_text(encoding="utf-8")
               for c in manifest["checks"]}
    return manifest, sources


def git_blob(value):
    raw = value.encode("utf-8")
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii")
                        + bytes([0]) + raw).hexdigest()


class CodeQAGate1PinnedPilotTests(unittest.TestCase):
    def test_actual_codeqa_witnesses_pass_without_independent_approval(self):
        manifest, sources = witness()
        self.assertEqual(manifest["consumer_repository"], "HyungseonSong-plasma/codeQA")
        self.assertEqual(manifest["revision"], "24040c02ea97056de89c6711e847b4f727fb0dcb")
        self.assertEqual(
            {c["id"]: c["blob_sha"] for c in manifest["checks"]},
            {"ccg_contract_id": "75a0116a87d7eb3929ac148b4d142c4764f53c87",
             "core_no_adapters_import": "0545d0266b9e9856f1be6ec875c46e23b7588655"},
        )
        for c in manifest["checks"]:
            self.assertEqual(git_blob(sources[c["path"]]), c["blob_sha"])
        result = run_gate1_manifest_v01(manifest=manifest, source_files=sources)
        self.assertEqual(result.status, "SCOPED_CHECKS_PASS")
        self.assertEqual(result.check_results,
                         {"ccg_contract_id": "PASS", "core_no_adapters_import": "PASS"})
        self.assertEqual(result.independent_approval, "REVIEW_REQUIRED")
        self.assertEqual(result.semantic_certification, "NOT_EVALUATED")

    def test_cli_runs_pinned_actual_snapshot_as_scoped_gate(self):
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main([
                "--manifest", str(MANIFEST),
                "--snapshot-root", str(FIXTURES),
            ])
        self.assertEqual(exit_code, 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["status"], "SCOPED_CHECKS_PASS")
        self.assertEqual(report["independent_approval"], "REVIEW_REQUIRED")
        self.assertEqual(report["semantic_certification"], "NOT_EVALUATED")

    def test_mutated_codeqa_source_fails_pinned_blob(self):
        manifest, sources = witness()
        sources["src/codeqa/core/graph.py"] += "import codeqa.adapters.python" + chr(10)
        result = run_gate1_manifest_v01(manifest=manifest, source_files=sources)
        self.assertIn("core_no_adapters_import:BLOB_MISMATCH", result.issues)
        self.assertNotEqual(result.status, "SCOPED_CHECKS_PASS")

    def test_mutated_schema_fails_pinned_blob(self):
        manifest, sources = witness()
        sources["contracts/ccg/graph-v0.1.schema.json"] = "{}"
        r = run_gate1_manifest_v01(manifest=manifest, source_files=sources)
        self.assertIn("ccg_contract_id:BLOB_MISMATCH", r.issues)

    def test_semantically_wrong_contract_is_rejected_even_with_matching_blob(self):
        manifest, sources = witness()
        manifest["checks"][0]["expected"] = "urn:incorrect"
        r = run_gate1_manifest_v01(manifest=manifest, source_files=sources)
        self.assertIn("ccg_contract_id:PREDICATE_FAILED", r.issues)

    def test_pinned_absent_required_source_cannot_pass(self):
        manifest, sources = witness()
        del sources["src/codeqa/core/graph.py"]
        r = run_gate1_manifest_v01(manifest=manifest, source_files=sources)
        self.assertIn("core_no_adapters_import:MISSING_CHECK", r.issues)
        self.assertEqual(r.check_results["core_no_adapters_import"], "NOT_EVALUATED")

    def test_synthetic_python_import_does_not_pass_predicate(self):
        manifest, sources = witness()
        path = "src/codeqa/core/graph.py"
        sources[path] += "import codeqa.adapters.python" + chr(10)
        # A new blob SHA can make bytes internally self-consistent; the
        # machine predicate must *still* reject a prohibited import.
        manifest["checks"][1]["blob_sha"] = git_blob(sources[path])
        r = run_gate1_manifest_v01(manifest=manifest, source_files=sources)
        self.assertIn("core_no_adapters_import:PREDICATE_FAILED", r.issues)

    def test_no_undeclared_source_or_duplicate_check(self):
        manifest, sources = witness()
        with self.assertRaises(LabelError):
            run_gate1_manifest_v01(
                manifest=manifest, source_files={**sources, "extra.py": "pass"})
        manifest["checks"].append(copy.deepcopy(manifest["checks"][0]))
        with self.assertRaises(LabelError):
            run_gate1_manifest_v01(manifest=manifest, source_files=sources)

    def test_unexpected_manifest_fields_fail_closed(self):
        manifest, sources = witness()
        manifest["independent_approval"] = "APPROVED"
        with self.assertRaises(LabelError):
            run_gate1_manifest_v01(manifest=manifest, source_files=sources)


if __name__ == "__main__":
    unittest.main()
