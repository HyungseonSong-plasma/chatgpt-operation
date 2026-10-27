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

    def test_cleanup_protects_open_pr_heads_and_main_at_write_time(self):
        text = self.text()
        self.assertIn('paged_pulls("open")', text)
        self.assertIn('def has_open_pr(branch: str) -> bool:', text)
        self.assertIn('if has_open_pr(branch):', text)
        self.assertIn('if branch == default_branch:', text)
        self.assertIn('default_branch = "main"', text)
        self.assertIn('protected_open_pr', text)

    def test_closed_pr_cleanup_uses_same_repository_head_evidence(self):
        text = self.text()
        self.assertIn('paged_pulls("closed")', text)
        self.assertIn('repo.get("full_name") != repository', text)
        self.assertIn('latest_closed_by_head.setdefault(branch, pull)', text)
        self.assertIn('expected_sha = pull["head"]["sha"]', text)

    def test_orphan_cleanup_requires_tip_to_be_fully_contained_in_main(self):
        text = self.text()
        self.assertIn('def paged_branches():', text)
        self.assertIn('main_sha = (main_ref.get("object") or {}).get("sha")', text)
        self.assertIn('f"/compare/{expected_sha}...{main_sha}"', text)
        self.assertIn('behind_by = int(comparison.get("behind_by", 0))', text)
        self.assertIn('if behind_by != 0:', text)
        self.assertIn('diverged.append(', text)
        self.assertIn('contained_deleted.append(', text)

    def test_cleanup_push_trigger_is_main_only(self):
        text = self.text()
        self.assertIn("branches:", text)
        self.assertIn("- main", text)

    def test_cleanup_has_bounded_permissions_and_serialization(self):
        text = self.text()
        self.assertIn('contents: write', text)
        self.assertIn('pull-requests: read', text)
        self.assertIn('group: samuel-closed-pr-branch-cleanup', text)
        self.assertIn('cancel-in-progress: false', text)


if __name__ == "__main__":
    unittest.main()
