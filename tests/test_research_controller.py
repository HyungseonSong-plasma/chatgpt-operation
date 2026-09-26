from chatgpt_operation.controller.research import (
    AnalysisResult,
    DecisionRisk,
    EscalationPolicy,
    HypothesisResult,
    ResearchStage,
    ResearchState,
    ResearchStateError,
    next_stage_from_analysis,
)


def test_research_state_persists_and_resumes(tmp_path):
    path = tmp_path / "research-state.json"
    state = ResearchState("r-1", "reduce runtime")
    assert state.apply_once("op-1", ResearchStage.ACQUIRE_KNOWLEDGE)
    state.save(path)

    resumed = ResearchState.load(path)
    assert resumed.stage is ResearchStage.ACQUIRE_KNOWLEDGE
    assert resumed.revision == 1
    assert resumed.completed_operation_ids == ["op-1"]
    assert resumed.apply_once("op-1", ResearchStage.GENERATE_HYPOTHESIS) is False
    assert resumed.stage is ResearchStage.ACQUIRE_KNOWLEDGE


def test_hypothesis_contract_rejects_invalid_confidence():
    try:
        HypothesisResult.from_dict({
            "statement": "solver cadence dominates cost",
            "mechanism": "excess solves",
            "falsification_test": "sweep cadence",
            "confidence": 1.5,
        })
    except ResearchStateError:
        pass
    else:
        raise AssertionError("invalid confidence must be rejected")


def test_analysis_routes_supported_to_decide():
    result = AnalysisResult.from_dict({
        "hypothesis_status": "supported",
        "confidence": 0.9,
    })
    assert next_stage_from_analysis(result) is ResearchStage.DECIDE


def test_analysis_routes_rejected_to_new_hypothesis():
    result = AnalysisResult.from_dict({
        "hypothesis_status": "rejected",
        "confidence": 0.8,
    })
    assert next_stage_from_analysis(result) is ResearchStage.GENERATE_HYPOTHESIS


def test_analysis_routes_inconclusive_to_more_experiment():
    result = AnalysisResult.from_dict({
        "hypothesis_status": "inconclusive",
        "confidence": 0.4,
    })
    assert next_stage_from_analysis(result) is ResearchStage.DESIGN_EXPERIMENT


def test_analysis_routes_knowledge_gap_before_status():
    result = AnalysisResult.from_dict({
        "hypothesis_status": "inconclusive",
        "confidence": 0.4,
        "knowledge_gap": True,
    })
    assert next_stage_from_analysis(result) is ResearchStage.ACQUIRE_KNOWLEDGE


def test_analysis_routes_high_consequence_ambiguity_to_escalation():
    result = AnalysisResult.from_dict({
        "hypothesis_status": "supported",
        "confidence": 0.7,
        "high_consequence_ambiguity": True,
    })
    assert next_stage_from_analysis(result) is ResearchStage.ESCALATE


def test_decision_risk_score_and_policy():
    risk = DecisionRisk.from_dict({
        "impact": 0.9,
        "uncertainty": 0.8,
        "irreversibility": 0.9,
    })
    assert risk.score == 0.648
    assert EscalationPolicy(threshold=0.5).requires_escalation(risk)


def test_analysis_routes_code_defined_risk_to_escalation():
    result = AnalysisResult.from_dict({
        "hypothesis_status": "supported",
        "confidence": 0.8,
        "decision_risk": {
            "impact": 0.9,
            "uncertainty": 0.8,
            "irreversibility": 0.9,
        },
    })
    assert next_stage_from_analysis(result) is ResearchStage.ESCALATE


def test_low_decision_risk_does_not_override_normal_route():
    result = AnalysisResult.from_dict({
        "hypothesis_status": "supported",
        "confidence": 0.8,
        "decision_risk": {
            "impact": 0.2,
            "uncertainty": 0.2,
            "irreversibility": 0.2,
        },
    })
    assert next_stage_from_analysis(result) is ResearchStage.DECIDE
