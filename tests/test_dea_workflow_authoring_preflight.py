"""DEA exact Workflow Draft planning checks: failure-closed, no authority."""
from __future__ import annotations

from dataclasses import replace
import copy
import json
from pathlib import Path
import unittest

from chatgpt_operation.controller.dea_workflow_authoring_preflight import (
    BRANCH, PATH, REPO, WORK_ID, WorkflowDraftIntent, assess_workflow_draft_intent,
)

BASE = Path(__file__).resolve().parents[1]
REF = (BASE / "docs/dea-v02-protected-producer-smoke.proposed.yml").read_bytes()
ORIGINAL = json.loads(
    (BASE / "automation/samuel/repository-mutation-policy.json").read_text()
)
SHA = "a" * 40


def policy_with_reviewed_scoped_exception() -> dict:
    p = copy.deepcopy(ORIGINAL)
    paths = p["mutation"]["file_paths"]
    if PATH not in paths["allow"]:
        paths["allow"].append(PATH)
    paths["deny"] = [x for x in paths["deny"] if x != ".github/workflows/**"]
    return p


def proposal():
    return WorkflowDraftIntent(
        repository=REPO,
        work_id=WORK_ID,
        path=PATH,
        action="create",
        branch=BRANCH,
        base_branch="main",
        expected_base_sha=SHA,
        draft=True,
        content=REF,
    )


def inspect(request=None, *, policy=None, source=REF, head=SHA):
    return assess_workflow_draft_intent(
        proposal() if request is None else request,
        observed_main_sha=head,
        trusted_reference_yaml=source,
        policy_document=(policy_with_reviewed_scoped_exception()
                         if policy is None else policy),
    )


class WorkflowDraftIntentTests(unittest.TestCase):
    def test_exact_proposal_is_never_automated_permission(self):
        result = inspect()
        self.assertEqual(
            result.status, "INTENT_MATCHES_PROPOSED_SCOPE_NOT_AUTHORIZED"
        )
        self.assertFalse(result.write_authorized)
        self.assertFalse(result.workflow_dispatch_authorized)
        self.assertFalse(result.merge_authorized)
        self.assertEqual(len(result.content_sha256), 64)

    def test_original_blanked_workflow_policy_does_not_enable_exception(self):
        if ".github/workflows/**" in ORIGINAL["mutation"]["file_paths"]["deny"]:
            result = inspect(policy=ORIGINAL)
            self.assertIn("EXACT_PATH_POLICY_NOT_ADOPTED", result.reasons)
        self.assertFalse(inspect(policy=ORIGINAL).write_authorized)

    def test_only_exact_file_create_is_in_scope(self):
        for changes in (
            {"path": ".github/workflows/ci.yml"},
            {"path": ".github/workflows/samuel-native-github.yml"},
            {"path": ".github/workflows/dea-evidence-producer.yml.bak"},
            {"action": "update"},
            {"action": "delete"},
        ):
            with self.subTest(changes=changes):
                out = inspect(replace(proposal(), **changes))
                self.assertIn(
                    "WRONG_WORKFLOW_PATH_OR_ACTION", out.reasons
                )
                self.assertFalse(out.write_authorized)

    def test_only_designated_work_id_and_repo(self):
        for changes in ({"repository": "other/repo"},
                        {"work_id": "new-case"}):
            with self.subTest(changes=changes):
                out = inspect(replace(proposal(), **changes))
                self.assertIn("WORK_IDENTITY_MISMATCH", out.reasons)

    def test_branch_draft_and_base_must_match(self):
        for changes in (
            {"branch": "main"},
            {"branch": "issue-254-producer-adoption-v2"},
            {"base_branch": "other"},
            {"draft": False},
        ):
            with self.subTest(changes=changes):
                out = inspect(replace(proposal(), **changes))
                self.assertIn("DRAFT_BRANCH_OR_BASE_MISMATCH", out.reasons)

    def test_current_base_sha_is_exact_pinned_fresh(self):
        for head in ("b" * 40, "HEAD", "", "A" * 40):
            with self.subTest(head=head):
                out = inspect(head=head)
                self.assertIn("STALE_OR_INVALID_MAIN_SHA", out.reasons)
        out = inspect(replace(proposal(), expected_base_sha="HEAD"))
        self.assertIn("STALE_OR_INVALID_MAIN_SHA", out.reasons)

    def test_signed_source_bytes_are_not_replaceable(self):
        for content in (b"", REF + b"\n", b"forged", b"A" * 65000):
            with self.subTest(content=content[:15]):
                out = inspect(replace(proposal(), content=content))
                self.assertIn(
                    "WORKFLOW_BYTES_NOT_EXACT_REVIEWED_SOURCE", out.reasons
                )
        out = inspect(source=b"forged")
        self.assertIn("WORKFLOW_BYTES_NOT_EXACT_REVIEWED_SOURCE", out.reasons)

    def test_wildcard_allow_and_other_workflow_paths_rejected(self):
        for additional in (".github/workflows/**",
                           ".github/workflows/ci.yml",
                           ".github/workflows/samuel-*.yml"):
            p = policy_with_reviewed_scoped_exception()
            p["mutation"]["file_paths"]["allow"].append(additional)
            with self.subTest(extra=additional):
                out = inspect(policy=p)
                self.assertIn("EXACT_PATH_POLICY_NOT_ADOPTED", out.reasons)

    def test_deny_override_and_main_mutation_bypass_rejected(self):
        p = policy_with_reviewed_scoped_exception()
        p["mutation"]["file_paths"]["deny"].append(".github/workflows/**")
        self.assertIn(
            "EXACT_PATH_POLICY_NOT_ADOPTED", inspect(policy=p).reasons
        )
        p = policy_with_reviewed_scoped_exception()
        p["mutation"]["branch_names"]["deny"] = []
        self.assertIn(
            "PROTECTED_MAIN_DENY_NOT_PRESERVED", inspect(policy=p).reasons
        )

    def test_malformed_or_foreign_policy_not_authorization(self):
        for p in ({}, None, {"repository": "elsewhere"}):
            with self.subTest(p=p):
                out = inspect(policy=p)
                self.assertIn("POLICY_UNAVAILABLE_OR_FOREIGN", out.reasons)
                self.assertFalse(out.write_authorized)

    def test_plain_approval_claim_cannot_make_this_enforcement(self):
        req = proposal()
        out = inspect(req)
        self.assertFalse(hasattr(out, "may_execute"))
        self.assertFalse(out.write_authorized)
        self.assertFalse(out.workflow_dispatch_authorized)


if __name__ == "__main__":
    unittest.main()
