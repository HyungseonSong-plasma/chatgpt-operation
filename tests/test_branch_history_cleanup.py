from __future__ import annotations

import pathlib
import unittest


WORKFLOW = pathlib.Path(
    ".github/workflows/samuel-branch-history-cleanup.yml"
)


class SamuelBranchHistoryCleanupTests(unittest.TestCase):
    def text(self) -> str:
        return WORKFLOW.read_text(encoding="utf-8")

    def test_cleanup_is_exact_sha_guarded_and_read_after_verified(self):
        text = self.text()
        self.assertIn('actual_sha != expected_sha', text)
        self.assertIn('request("DELETE", delete_path)', text)
        self.assertIn('for attempt in range(6)', text)
        self.assertIn('time.sleep(1)', text)
        self.assertIn('post-delete verification timed out', text)
        self.assertIn('branch changed/reappeared after delete', text)
        self.assertIn('allow_not_found=True', text)

    def test_cleanup_protects_open_pr_heads_and_main(self):
        text = self.text()
        self.assertIn('paged_pulls("open")', text)
        self.assertIn('branch in open_heads', text)
        self.assertIn('branch == default_branch', text)
        self.assertIn('default_branch = "main"', text)

    def test_cleanup_only_uses_same_repository_closed_pr_heads(self):
        text = self.text()
        self.assertIn('paged_pulls("closed")', text)
        self.assertIn('repo.get("full_name") != repository', text)
        self.assertIn('latest_closed_by_head.setdefault(branch, pull)', text)

    def test_cleanup_has_bounded_permissions_and_serialization(self):
        text = self.text()
        self.assertIn('contents: write', text)
        self.assertIn('pull-requests: read', text)
        self.assertIn('group: samuel-closed-pr-branch-cleanup', text)
        self.assertIn('cancel-in-progress: false', text)


if __name__ == "__main__":
    unittest.main()
