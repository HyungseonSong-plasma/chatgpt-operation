import pathlib
import unittest


WORKFLOW = pathlib.Path(".github/workflows/cleanup-cancelled-runs.yml")


class ActionsHistoryCleanupTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_samuel_bootstrap_completion_triggers_cleanup(self):
        self.assertIn("workflow_run:", self.text)
        self.assertIn("- Samuel Bootstrap", self.text)
        self.assertIn("- completed", self.text)

    def test_cleanup_has_actions_write_authority(self):
        self.assertIn("actions: write", self.text)
        self.assertIn("contents: read", self.text)

    def test_cleanup_deletes_only_cancelled_and_skipped_snapshots(self):
        self.assertIn("for conclusion in cancelled skipped; do", self.text)
        self.assertIn("select(.status == \\\"completed\\\"", self.text)
        self.assertNotIn("for conclusion in success", self.text)
        self.assertNotIn("for conclusion in failure", self.text)
        self.assertNotIn("for conclusion in timed_out", self.text)

    def test_cleanup_verifies_the_initial_snapshot_only(self):
        self.assertIn('comm -12 "$snapshot_ids" "$current_ids"', self.text)
        self.assertIn('test "$remaining" = "0"', self.text)
        self.assertIn('test "$run_id" != "$GITHUB_RUN_ID"', self.text)


if __name__ == "__main__":
    unittest.main()
