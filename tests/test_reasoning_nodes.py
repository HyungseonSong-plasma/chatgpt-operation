from chatgpt_operation.controller.reasoning import (
    ReasoningNodeError,
    ReasoningRequest,
    analysis_node,
    hypothesis_node,
)


def test_hypothesis_node_returns_typed_result():
    def runner(task, context, attempt, validation_error):
        assert task == "generate hypothesis"
        assert context["objective"] == "reduce runtime"
        assert attempt == 1
        assert validation_error is None
        return {
            "statement": "solver cadence dominates cost",
            "mechanism": "excess solves",
            "falsification_test": "sweep cadence",
            "confidence": 0.7,
        }

    result = hypothesis_node().run(
        ReasoningRequest(
            task="generate hypothesis",
            context={"objective": "reduce runtime"},
        ),
        runner,
    )
    assert result.statement == "solver cadence dominates cost"
    assert result.confidence == 0.7


def test_reasoning_node_repairs_invalid_first_output():
    calls = []

    def runner(task, context, attempt, validation_error):
        calls.append((attempt, validation_error))
        if attempt == 1:
            return {
                "statement": "x",
                "mechanism": "y",
                "falsification_test": "z",
                "confidence": 1.5,
            }
        assert validation_error is not None
        return {
            "statement": "x",
            "mechanism": "y",
            "falsification_test": "z",
            "confidence": 0.6,
        }

    result = hypothesis_node(max_attempts=2).run(
        ReasoningRequest(task="generate hypothesis", context={}),
        runner,
    )
    assert result.confidence == 0.6
    assert [item[0] for item in calls] == [1, 2]
    assert calls[1][1] is not None


def test_reasoning_node_fails_after_bounded_attempts():
    def runner(task, context, attempt, validation_error):
        return {
            "hypothesis_status": "unknown",
            "confidence": 0.5,
        }

    try:
        analysis_node(max_attempts=2).run(
            ReasoningRequest(task="analyze", context={}),
            runner,
        )
    except ReasoningNodeError as exc:
        assert "after 2 attempts" in str(exc)
    else:
        raise AssertionError("invalid structured output must fail closed")


def test_non_mapping_output_is_repaired():
    def runner(task, context, attempt, validation_error):
        if attempt == 1:
            return "not structured"
        assert validation_error == "reasoning runner must return an object"
        return {
            "hypothesis_status": "supported",
            "confidence": 0.9,
        }

    result = analysis_node(max_attempts=2).run(
        ReasoningRequest(task="analyze", context={}),
        runner,
    )
    assert result.hypothesis_status == "supported"


def test_reasoning_request_rejects_invalid_context():
    try:
        ReasoningRequest(task="analyze", context=None)
    except ReasoningNodeError:
        pass
    else:
        raise AssertionError("reasoning context must be an object")
