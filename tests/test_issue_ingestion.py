import pytest

from chatgpt_operation.controller.issue_ingestion import (
    ADMISSION_MARKER, AdmissionError, admit_issue, decode_admission_ledger,
)

def issue(number=100, labels=("samuel",), title="Implement deterministic work"):
    return {
        "number": number,
        "title": title,
        "body": "Acceptance criteria",
        "html_url": f"https://github.com/o/r/issues/{number}",
        "labels": [{"name": x} for x in labels],
    }

def test_admits_labeled_issue_with_deterministic_identity():
    write=admit_issue([],issue())
    assert write["changed"] is True
    assert write["work_id"] == "issue:100"
    ledger=decode_admission_ledger(write["body"])
    assert ledger["issue:100"]["issue_number"] == 100
    assert ledger["issue:100"]["status"] == "admitted"

def test_replay_is_noop():
    first=admit_issue([],issue())
    comments=[{"id":7,"body":first["body"]}]
    second=admit_issue(comments,issue())
    assert second["changed"] is False
    assert second["comment_id"] == 7
    assert second["body"] == first["body"]

def test_requires_explicit_samuel_label():
    with pytest.raises(AdmissionError,match="explicitly admitted"):
        admit_issue([],issue(labels=("bug",)))

def test_rejects_changed_identity_after_admission():
    first=admit_issue([],issue())
    with pytest.raises(AdmissionError,match="identity changed"):
        admit_issue([{"id":7,"body":first["body"]}],issue(title="Changed title"))

def test_rejects_multiple_authoritative_ledgers():
    body=ADMISSION_MARKER+"\n~~~json\n{\"schema_version\":1,\"work\":{}}\n~~~"
    with pytest.raises(AdmissionError,match="multiple authoritative"):
        admit_issue([{"id":1,"body":body},{"id":2,"body":body}],issue())
