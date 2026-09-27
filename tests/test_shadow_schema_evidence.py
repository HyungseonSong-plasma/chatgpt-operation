import unittest
from chatgpt_operation.controller.reasoning_qualification import QualificationCase, QualificationFailure, evaluate_shadow

class BadProvider:
    name="bad"
    def reason(self, **kwargs):
        return {
            "operation":"analyze",
            "decision_id":"github_execution_authority",
            "compatible_with_locked_decisions":True,
            "revision_requested":False,
            "action_plan":None,
            "unexpected_field":"diagnostic",
        }

class ShadowSchemaEvidenceTests(unittest.TestCase):
    def test_schema_error_preserves_raw_proposal(self):
        result=evaluate_shadow(
            provider=BadProvider(),
            case=QualificationCase("schema",{},allowed_decision_ids=("github_execution_authority",)),
        )
        self.assertFalse(result.passed)
        self.assertFalse(result.executed)
        self.assertEqual(result.failures,(QualificationFailure.SCHEMA_INVALID,))
        self.assertEqual(result.schema_error,"unknown Issue reasoning proposal fields")
        self.assertEqual(result.raw_proposal["unexpected_field"],"diagnostic")

if __name__=="__main__":
    unittest.main()
