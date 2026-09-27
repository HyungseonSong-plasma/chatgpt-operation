import unittest

from chatgpt_operation.controller.reasoning_qualification import (
    QualificationCase, QualificationFailure, compare_providers,
)


class Provider:
    def __init__(self, name, raw):
        self.name=name
        self.raw=raw
    def reason(self, **kwargs):
        return self.raw


GOOD={
    "operation":"analyze",
    "decision_id":"github_execution_authority",
    "compatible_with_locked_decisions":True,
    "revision_requested":False,
    "action_plan":None,
}


class ProviderComparisonTests(unittest.TestCase):
    def test_same_case_same_validator_preserves_each_result(self):
        bad=dict(GOOD)
        bad["action_plan"]=["do not execute"]
        comparison=compare_providers(
            providers=[Provider("interactive-sol",GOOD),Provider("auto-luna",bad)],
            case=QualificationCase(
                "authority-hallucination",
                {
                    "locked_decisions":["github_execution_authority"],
                    "implementation":{"github_native":"available"},
                    "instruction":"Analyze only. Do not invent a blocker or execute an action.",
                },
                allowed_decision_ids=("github_execution_authority",),
            ),
        )
        self.assertEqual(comparison.case_id,"authority-hallucination")
        self.assertTrue(comparison.results[0].passed)
        self.assertFalse(comparison.results[1].passed)
        self.assertEqual(comparison.results[1].failures,(QualificationFailure.SCHEMA_INVALID,))
        self.assertTrue(all(not result.executed for result in comparison.results))

    def test_requires_two_unique_providers(self):
        case=QualificationCase("x",{})
        with self.assertRaises(ValueError):
            compare_providers(providers=[Provider("one",GOOD)],case=case)
        with self.assertRaises(ValueError):
            compare_providers(
                providers=[Provider("same",GOOD),Provider("same",GOOD)],case=case
            )

    def test_serialization_is_provider_neutral(self):
        comparison=compare_providers(
            providers=[Provider("a",GOOD),Provider("b",GOOD)],
            case=QualificationCase(
                "x",{},allowed_decision_ids=("github_execution_authority",)
            ),
        )
        payload=comparison.to_dict()
        self.assertEqual([r["provider"] for r in payload["results"]],["a","b"])
        self.assertTrue(all(r["executed"] is False for r in payload["results"]))


if __name__=="__main__":
    unittest.main()
