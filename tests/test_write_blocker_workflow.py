import pathlib
import unittest


class WriteBlockerWorkflowContractTests(unittest.TestCase):
    def test_workflow_denies_issue_write_and_requires_real_403(self):
        text = pathlib.Path(".github/workflows/samuel-write-blocker-qualification.yml").read_text()
        self.assertIn("permissions:\n  contents: read", text)
        self.assertNotIn("issues: write", text)
        self.assertIn('test "$code" = "403"', text)
        self.assertIn('"continuation":"RETRY"', text)
        self.assertIn("samuel-qualification-checkpoint.json", text)
        self.assertIn("actions/upload-artifact@v4", text)


if __name__ == "__main__":
    unittest.main()
