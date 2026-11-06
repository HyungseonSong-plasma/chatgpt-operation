"""Gate 1 source predicates never grant Gate 2 independent approval."""
import hashlib
import unittest

from chatgpt_operation.documentation.semantic_gates_v01 import verify_automated_gate_v01
from chatgpt_operation.documentation.status_labels import LabelError

SHA = "a" * 40


def make_check(**updates):
    source = '{"$id":"urn:codeqa:ccg:graph:v0.1"}'
    raw = source.encode()
    c = {
        "kind": "JSON_POINTER_EQUALS",
        "repository": "owner/consumer",
        "revision": SHA,
        "scope": "ccg-v01",
        "path": "contracts/ccg/graph.json",
        "blob_sha": hashlib.sha1(b"blob " + str(len(raw)).encode() +
                                 bytes([0]) + raw).hexdigest(),
        "content": source,
        "subject": "/$id",
        "expected": "urn:codeqa:ccg:graph:v0.1",
    }
    c.update(updates)
    return c


def run(checks=None, required_checks=("ccg",), **updates):
    args = {"repository": "owner/consumer", "revision": SHA,
            "scope": "ccg-v01", "required_checks": required_checks,
            "checks": {"ccg": make_check()} if checks is None else checks}
    args.update(updates)
    return verify_automated_gate_v01(**args)


class SemanticGateTests(unittest.TestCase):
    def test_pass_cannot_approve(self):
        r = run()
        self.assertEqual(r.status, "SCOPED_CHECKS_PASS")
        self.assertEqual(r.check_results["ccg"], "PASS")
        self.assertEqual(r.independent_approval, "REVIEW_REQUIRED")
        self.assertEqual(r.semantic_certification, "NOT_EVALUATED")

    def test_changed_bytes(self):
        r = run(checks={"ccg": make_check(content="{}")})
        self.assertIn("ccg:BLOB_MISMATCH", r.issues)

    def test_wrong_contract(self):
        r = run(checks={"ccg": make_check(expected="urn:wrong")})
        self.assertIn("ccg:PREDICATE_FAILED", r.issues)

    def test_binding(self):
        for key, value in (("repository", "other/repo"),
                           ("revision", "b"*40), ("scope", "different")):
            with self.subTest(key=key):
                r = run(checks={"ccg": make_check(**{key: value})})
                self.assertIn("ccg:BOUNDARY_MISMATCH", r.issues)

    def test_missing_check(self):
        r = run(required_checks=("ccg", "source"))
        self.assertIn("source:MISSING_CHECK", r.issues)

    def test_unsupported(self):
        r = run(checks={"ccg": make_check(kind="UNSUPPORTED")})
        self.assertIn("ccg:UNSUPPORTED_PREDICATE", r.issues)

    def test_scope_and_path_are_strict(self):
        with self.assertRaises(LabelError):
            run(revision="main")
        with self.assertRaises(LabelError):
            run(required_checks=())
        r = run(checks={"ccg": make_check(path="../unsafe.json")})
        self.assertIn("ccg:UNSAFE_PATH", r.issues)

    def test_python_import_absence_and_presence(self):
        for source, expected in (
            ("import json\\n", "SCOPED_CHECKS_PASS"),
            ("import codeqa.adapters.python\\n", "REVIEW_REQUIRED"),
        ):
            with self.subTest(source=source):
                raw = source.encode("utf-8")
                blob = hashlib.sha1(
                    b"blob " + str(len(raw)).encode() + bytes([0]) + raw
                ).hexdigest()
                check = make_check(kind="PYTHON_IMPORT_ABSENT",
                                   path="src/codeqa/core/example.py",
                                   subject="codeqa.adapters",
                                   content=source, blob_sha=blob)
                r = run(checks={"ccg": check})
                self.assertEqual(r.status, expected)
                self.assertEqual(r.independent_approval, "REVIEW_REQUIRED")

    def test_unresolved_relative_import_stays_unverified(self):
        source = "from .internal import helper\\n"
        raw = source.encode("utf-8")
        blob = hashlib.sha1(
            b"blob " + str(len(raw)).encode() + bytes([0]) + raw
        ).hexdigest()
        r = run(checks={"ccg": make_check(
            kind="PYTHON_IMPORT_ABSENT",
            path="src/codeqa/core/example.py",
            subject="codeqa.adapters", content=source, blob_sha=blob)})
        self.assertIn("ccg:UNVERIFIABLE_PREDICATE", r.issues)

    def test_check_cannot_supply_approval(self):
        c = make_check(approved="true", reviewer="not-an-authenticated-review")
        r = run(checks={"ccg": c})
        self.assertEqual(r.status, "SCOPED_CHECKS_PASS")
        self.assertEqual(r.independent_approval, "REVIEW_REQUIRED")



if __name__ == "__main__":
    unittest.main()
