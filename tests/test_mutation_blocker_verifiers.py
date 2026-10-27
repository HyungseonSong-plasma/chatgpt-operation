"""Read-only GitHub clearance validator adversarial tests."""
import unittest

from chatgpt_operation.repository.blocker_resolution import (
    ClearanceEvidence, ClearanceKind,
)
from chatgpt_operation.repository.blocker_verifiers import TrustedGitHubReadbacks

SHA = "a" * 40
REPO = "HyungseonSong-plasma/chatgpt-operation"
BRANCH = "samuel/236-mutation-blocker-taxonomy"
INTENT = "f" * 64


class Fake:
    def __init__(self):
        self.fail = False
        self.reads = []
        self.data = {
            "/git/ref/heads/" + BRANCH: {
                "ref": "refs/heads/" + BRANCH, "object": {"sha": SHA},
            },
            "/actions/runs/123": {
                "id": 123, "status": "completed", "conclusion": "success",
                "head_sha": SHA, "repository": {"full_name": REPO},
            },
        }

    def get(self, path, *, query=None):
        self.reads.append(path)
        if self.fail:
            raise RuntimeError("readback unavailable")
        return self.data[path]


def proof(kind, ref, head=SHA):
    return ClearanceEvidence(INTENT, "original-blocker", kind, head, ref)


class TrustedGitHubReadbackTests(unittest.TestCase):
    def setUp(self):
        self.transport = Fake()
        self.reader = TrustedGitHubReadbacks(
            self.transport, repository=REPO, branch=BRANCH,
        )

    def test_sha_replan_requires_true_exact_head_and_readback_reference(self):
        self.assertTrue(self.reader.verify_technical(
            proof(ClearanceKind.SHA_REPLANNED, "github-head:" + BRANCH + "@" + SHA)))
        self.assertFalse(self.reader.verify_technical(
            proof(ClearanceKind.SHA_REPLANNED, "self-attested")))
        self.assertFalse(self.reader.verify_technical(
            proof(ClearanceKind.SHA_REPLANNED, "github-head:" + BRANCH + "@" + SHA,
                  head="b" * 40)))

    def test_ci_success_requires_exact_run_head_repository_and_status(self):
        p = proof(ClearanceKind.EXACT_HEAD_CI_PASS, "github-actions-run:123")
        self.assertTrue(self.reader.verify_technical(p))
        for changes in (
            {"status": "queued"},
            {"conclusion": "failure"},
            {"head_sha": "b" * 40},
            {"repository": {"full_name": "other/repo"}},
            {"id": 124},
        ):
            with self.subTest(changes=changes):
                original = dict(self.transport.data["/actions/runs/123"])
                self.transport.data["/actions/runs/123"].update(changes)
                self.assertFalse(self.reader.verify_technical(p))
                self.transport.data["/actions/runs/123"] = original

    def test_self_reported_success_without_real_run_never_clears(self):
        for ref in ("PASS", "github-actions-run:0", "github-actions-run:abc",
                    "https://github.com/other/repo/actions/runs/123",
                    "github-actions-run:999"):
            with self.subTest(ref=ref):
                self.assertFalse(self.reader.verify_technical(
                    proof(ClearanceKind.EXACT_HEAD_CI_PASS, ref)))

    def test_unknown_provenance_review_permissions_are_not_self_attested(self):
        for kind in (ClearanceKind.WORKFLOW_PROVENANCE_PASS,
                     ClearanceKind.CURRENT_HEAD_REVIEW,
                     ClearanceKind.TARGET_ACCESS_RESTORED,
                     ClearanceKind.UPSTREAM_SAFETY_CLEARED,
                     ClearanceKind.OWNER_POLICY_AUTHORIZED):
            with self.subTest(kind=kind):
                self.assertFalse(self.reader.verify_technical(proof(kind, "claimed-ok")))
        self.assertFalse(self.reader.verify_authority(
            proof(ClearanceKind.UPSTREAM_SAFETY_CLEARED, "claimed-clear")))

    def test_readback_failure_denies_auto_release(self):
        self.transport.fail = True
        self.assertFalse(self.reader.verify_technical(
            proof(ClearanceKind.EXACT_HEAD_CI_PASS, "github-actions-run:123")))

    def test_transient_recovery_is_scoped_to_healthy_exact_head(self):
        ref = "github-head:" + BRANCH + "@" + SHA
        self.assertTrue(self.reader.verify_technical(
            proof(ClearanceKind.TRANSIENT_RECOVERED, ref)))
        self.transport.data["/git/ref/heads/" + BRANCH]["object"]["sha"] = "b" * 40
        self.assertFalse(self.reader.verify_technical(
            proof(ClearanceKind.TRANSIENT_RECOVERED, ref)))

    def test_invalid_configuration_refused(self):
        for repo, branch in (("bad", BRANCH), (REPO, "../main"), (REPO, "/main")):
            with self.subTest(repo=repo, branch=branch), self.assertRaises(ValueError):
                TrustedGitHubReadbacks(Fake(), repository=repo, branch=branch)


if __name__ == "__main__":
    unittest.main()
