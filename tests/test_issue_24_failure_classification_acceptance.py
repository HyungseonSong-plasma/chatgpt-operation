from __future__ import annotations

from chatgpt_operation.workflow_failure_ingestion import classify_failure


def test_external_dependency_is_distinguished_from_repository_and_unknown_failures() -> None:
    external = {
        "dependency_status": "external",
        "failure_signature": "dependency-502",
    }
    repository = {"repository_test_failure": "true"}
    skill = {"central_skill_contract_failure": "true"}
    ambiguous = {}

    assert classify_failure(external) == "EXTERNAL_DEPENDENCY_FAILURE"
    assert classify_failure(repository) == "REPOSITORY_TEST_FAILURE"
    assert classify_failure(skill) == "CENTRAL_SKILL_CONTRACT_FAILURE"
    assert classify_failure(ambiguous) == "UNKNOWN"
