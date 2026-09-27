import unittest

from chatgpt_operation.controller.reasoning_qualification import (
    QualificationCase, QualificationFailure, evaluate_shadow, qualify,
)


class FakeProvider:
    name = "fake-luna"

    def __init__(self, raw):
        self.raw = raw

    def reason(self, **kwargs):
        return self.raw


def valid(decision_id="github_execution_authority"):
    return {
        "operation": "analyze",
        "decision_id": decision_id,
        "compatible_with_locked_decisions": True,
        "revision_requested": False,
        "action_plan": None,
    }


class ReasoningQualificationTests(unittest.TestCase):
    def case(self):
        return QualificationCase(
            "authority-hallucination",
            {"implementation": {"github_native": "available"}},
            allowed_decision_ids=("github_execution_authority",),
            evidence_ids=("obs-1",),
        )

    def test_shadow_never_executes(self):
        result = evaluate_shadow(provider=FakeProvider(valid()), case=self.case())
        self.assertTrue(result.passed)
        self.assertFalse(result.executed)

    def test_schema_failure_is_typed(self):
        result = evaluate_shadow(
            provider=FakeProvider({"operation": "invent-authority"}), case=self.case()
        )
        self.assertEqual(result.failures, (QualificationFailure.SCHEMA_INVALID,))

    def test_decision_drift_is_rejected(self):
        result = evaluate_shadow(
            provider=FakeProvider(valid("invented-decision")), case=self.case()
        )
        self.assertIn(QualificationFailure.DECISION_DRIFT, result.failures)

    def test_empty_suite_fails_closed(self):
        with self.assertRaises(ValueError):
            qualify(FakeProvider(valid()), [])


if __name__ == "__main__":
    unittest.main()
