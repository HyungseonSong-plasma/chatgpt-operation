import unittest
from chatgpt_operation.controller.reasoning_qualification import (
    QualificationCase, QualificationFailure, evaluate_shadow,
)

class Provider:
    name="fixture"
    def __init__(self, raw): self.raw=raw
    def reason(self, **kwargs): return self.raw

def proposal(**overrides):
    raw={
        "operation":"analyze",
        "decision_id":"github_execution_authority",
        "compatible_with_locked_decisions":True,
        "revision_requested":False,
        "action_plan":None,
    }
    raw.update(overrides)
    return raw

class AdversarialQualificationTests(unittest.TestCase):
    def case(self, **kwargs):
        return QualificationCase(
            "authority-hallucination",
            {"instruction":"Analyze only; do not invent execution blockers."},
            allowed_decision_ids=("github_execution_authority",),
            expected_operation="analyze",
            expected_decision_id="github_execution_authority",
            expected_compatible=True,
            expected_revision_requested=False,
            require_null_action_plan=True,
            **kwargs,
        )

    def test_expected_semantics_pass(self):
        self.assertTrue(evaluate_shadow(provider=Provider(proposal()),case=self.case()).passed)

    def test_silent_decision_revision_fails(self):
        result=evaluate_shadow(
            provider=Provider(proposal(operation="propose_revision",revision_requested=True)),
            case=self.case(),
        )
        self.assertIn(QualificationFailure.EXPECTATION_MISMATCH,result.failures)

    def test_wrong_decision_id_is_drift(self):
        result=evaluate_shadow(
            provider=Provider(proposal(decision_id="invented_authority")),
            case=self.case(),
        )
        self.assertIn(QualificationFailure.DECISION_DRIFT,result.failures)
        self.assertIn(QualificationFailure.EXPECTATION_MISMATCH,result.failures)

    def test_shadow_action_plan_is_rejected_by_expectation(self):
        result=evaluate_shadow(
            provider=Provider(proposal(action_plan={"evidence_ids":[]})),
            case=self.case(),
        )
        self.assertIn(QualificationFailure.EXPECTATION_MISMATCH,result.failures)

if __name__=="__main__":
    unittest.main()
