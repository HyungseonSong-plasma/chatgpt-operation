from chatgpt_operation.github.actions_runtime import (
    ActionsRuntimeError,
    execution_result_artifact_metadata,
)


def test_execution_result_artifact_requires_exactly_one_live_typed_result():
    class ArtifactTransport:
        def get(self, path, query=None):
            return {"artifacts": [
                {"id": 7, "name": "samuel-execution-result-123", "expired": False}
            ]}
    meta = execution_result_artifact_metadata(ArtifactTransport(), 123)
    assert meta["id"] == 7


def test_execution_result_artifact_rejects_ambiguity():
    class ArtifactTransport:
        def get(self, path, query=None):
            return {"artifacts": [
                {"id": 7, "name": "samuel-execution-result-123", "expired": False},
                {"id": 8, "name": "samuel-execution-result-123-copy", "expired": False},
            ]}
    try:
        execution_result_artifact_metadata(ArtifactTransport(), 123)
    except ActionsRuntimeError as exc:
        assert "exactly one" in str(exc)
    else:
        raise AssertionError("ambiguous corrective artifacts must fail closed")
