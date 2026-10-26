from __future__ import annotations

import json
import unittest
from pathlib import Path


CONTRACT = Path("skills/problem-oriented-response/contract.json")
README = Path("skills/problem-oriented-response/README.md")
BOOTSTRAP = Path("skills/session-bootstrap/README.md")
EVOLUTION = Path("docs/operating_system/EVOLUTION.md")


class ProblemOrientedResponseTests(unittest.TestCase):
    def test_machine_contract_is_problem_first_and_detail_on_request(self):
        payload = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(
            payload["contract_id"], "samuel.problem-first-response.v1"
        )
        self.assertEqual(payload["mode"], "problem_first")
        self.assertEqual(payload["detail_policy"], "on_request")
        self.assertEqual(payload["resolved_items"], "omit_by_default")
        self.assertTrue(payload["human_review_requires_question"])
        self.assertEqual(
            payload["default_problem_fields"],
            [
                "problem_id",
                "problem",
                "state",
                "human_review",
                "review_question",
            ],
        )

    def test_skill_requires_unresolved_problem_and_human_review_projection(self):
        text = README.read_text(encoding="utf-8")
        self.assertIn("What is still unresolved?", text)
        self.assertIn("Which unresolved items require human judgment?", text)
        self.assertIn("review_question", text)
        self.assertIn("Detail-on-request rule", text)
        self.assertIn("BLOCKED_RESPONSE_CONTRACT", text)

    def test_session_bootstrap_makes_response_contract_mandatory(self):
        text = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn(
            "skills/problem-oriented-response/contract.json",
            text,
        )
        self.assertIn("BLOCKED_RESPONSE_CONTRACT", text)
        self.assertIn(
            "response_contract = samuel.problem-first-response.v1",
            text,
        )

    def test_david_promotion_is_gated_by_codeqa_stability(self):
        text = EVOLUTION.read_text(encoding="utf-8")
        self.assertIn("codeQA", text)
        self.assertIn("David shadow", text)
        self.assertIn("David audited", text)
        self.assertIn("explicit owner promotion", text)
        self.assertIn("problem-first", text)


if __name__ == "__main__":
    unittest.main()
