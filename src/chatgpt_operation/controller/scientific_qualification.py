"""Deterministic qualification of scientific-analysis continuation."""
from __future__ import annotations
from dataclasses import dataclass

from .research import AnalysisResult, ResearchStage, next_stage_from_analysis


@dataclass(frozen=True)
class ScientificQualificationResult:
    case_id: str
    passed: bool
    expected: ResearchStage
    actual: ResearchStage
    hypothesis_status: str


def qualify_analysis_transition(
    *, case_id: str, analysis: AnalysisResult, expected: ResearchStage
) -> ScientificQualificationResult:
    actual = next_stage_from_analysis(analysis)
    return ScientificQualificationResult(
        case_id=case_id,
        passed=actual is expected,
        expected=expected,
        actual=actual,
        hypothesis_status=analysis.hypothesis_status,
    )


def contradicted_hypothesis_case() -> ScientificQualificationResult:
    """Contradictory evidence must revise the hypothesis, not proceed to decision."""
    analysis = AnalysisResult.from_dict({
        "hypothesis_status": "rejected",
        "confidence": 1.0,
        "knowledge_gap": False,
        "additional_experiment_needed": False,
        "high_consequence_ambiguity": False,
    })
    return qualify_analysis_transition(
        case_id="scientific-evidence-rejects-hypothesis",
        analysis=analysis,
        expected=ResearchStage.GENERATE_HYPOTHESIS,
    )
