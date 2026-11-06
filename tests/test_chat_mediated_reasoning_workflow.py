"""Regression gates for ChatGPT-authored external Samuel reasoning."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ChatMediatedReasoningWorkflowTests(unittest.TestCase):
    def test_production_bootstrap_never_injects_llm_api_key(self):
        bootstrap=(ROOT/".github/workflows/samuel-bootstrap.yml").read_text()
        self.assertIn("SAMUEL_REASONING_MODE: EXTERNAL",bootstrap)
        self.assertIn("SAMUEL_REASONING_TRUSTED_AUTHOR: HyungseonSong-plasma",bootstrap)
        self.assertNotIn("OPENAI_API_KEY:",bootstrap)
        self.assertNotIn("SAMUEL_OPENAI_MODEL:",bootstrap)
        self.assertNotIn("SAMUEL_REASONING_MODE: AUTO_WITH_AUDIT",bootstrap)

    def test_reasoning_wake_is_owner_scoped_to_central_ledger(self):
        wake=(ROOT/".github/workflows/samuel-reasoning-wake.yml").read_text()
        self.assertIn("github.event.issue.number == 44",wake)
        self.assertIn("github.event.comment.user.login == 'HyungseonSong-plasma'",wake)
        self.assertIn("<!-- samuel-reasoning-submission -->",wake)
        self.assertIn("actions: write",wake)

    def test_chat_submission_verification_is_code_owned(self):
        path=ROOT/"src/chatgpt_operation/controller/reasoning_submission.py"
        code=path.read_text()
        self.assertIn('user.get("login") != trusted_author',code)
        self.assertIn('return None',code)
        self.assertIn('multiple reasoning submissions for work',code)


if __name__=="__main__":
    unittest.main()
