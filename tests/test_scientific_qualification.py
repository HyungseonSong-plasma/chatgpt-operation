import unittest
from chatgpt_operation.controller.research import AnalysisResult, ResearchStage
from chatgpt_operation.controller.scientific_qualification import (
    contradicted_hypothesis_case, insufficient_information_case, qualify_analysis_transition,
)

class ScientificQualificationTests(unittest.TestCase):
    def test_rejected_hypothesis_forces_hypothesis_revision(self):
        q=contradicted_hypothesis_case()
        self.assertTrue(q.passed)
        self.assertEqual(q.actual,ResearchStage.GENERATE_HYPOTHESIS)

    def test_rejected_hypothesis_cannot_silently_decide(self):
        analysis=AnalysisResult.from_dict({
            "hypothesis_status":"rejected","confidence":0.95,
            "knowledge_gap":False,"additional_experiment_needed":False,
            "high_consequence_ambiguity":False,
        })
        q=qualify_analysis_transition(
            case_id="negative-control",analysis=analysis,expected=ResearchStage.DECIDE
        )
        self.assertFalse(q.passed)
        self.assertEqual(q.actual,ResearchStage.GENERATE_HYPOTHESIS)

    def test_knowledge_gap_precedes_hypothesis_revision(self):
        analysis=AnalysisResult.from_dict({
            "hypothesis_status":"rejected","confidence":0.5,
            "knowledge_gap":True,"additional_experiment_needed":False,
            "high_consequence_ambiguity":False,
        })
        q=qualify_analysis_transition(
            case_id="missing-knowledge",analysis=analysis,
            expected=ResearchStage.ACQUIRE_KNOWLEDGE,
        )
        self.assertTrue(q.passed)

    def test_insufficient_information_acquires_knowledge(self):
        q=insufficient_information_case()
        self.assertTrue(q.passed)
        self.assertEqual(q.actual,ResearchStage.ACQUIRE_KNOWLEDGE)

    def test_high_consequence_insufficient_information_escalates(self):
        q=insufficient_information_case(high_consequence=True)
        self.assertTrue(q.passed)
        self.assertEqual(q.actual,ResearchStage.ESCALATE)
        self.assertNotEqual(q.actual,ResearchStage.DECIDE)

if __name__=="__main__":
    unittest.main()
