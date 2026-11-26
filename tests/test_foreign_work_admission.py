from dataclasses import replace

import pytest

from chatgpt_operation.controller.foreign_work_admission import (
    AdmissionStatus, EnrollmentRecord, ForeignAdmissionBinding, ForeignWorkAdmission,
)
from chatgpt_operation.repository.legacy_work_identity import (
    HistoricalRecord, HistoryEvidence, LegacyWorkScope, RecoveryRequest,
)

HEAD = "a" * 40
PIN = "b" * 40
ISSUER = "test-authority"  # Synthetic only; never a production identity.


class FakeTransport:
    def __init__(self, binding, head=HEAD):
        self.binding = binding
        self.head = head
        self.reads = []
        self.mutate = lambda path, data: data

    def get(self, path):
        self.reads.append(path)
        b = self.binding
        root = "/repos/" + b.scope.repository
        if path == root:
            data = {"id": b.scope.repository_id, "full_name": b.scope.repository}
        elif path == root + "/issues/" + str(b.issue_number):
            data = {"id": b.scope.issue_id, "number": b.issue_number,
                    "state": "open", "url": "https://api.github.com" + path}
        elif path == root + "/git/ref/heads/" + b.target_branch:
            data = {"ref": "refs/heads/" + b.target_branch,
                    "object": {"type": "commit", "sha": self.head}}
        else:
            raise AssertionError(path)
        return self.mutate(path, data)


def fixture(repo="example/moose", repo_id=10, issue_id=20):
    scope = LegacyWorkScope(repo, repo_id, issue_id, "existing-scope")
    b = ForeignAdmissionBinding(scope, 888, "issue-888/runtime", PIN, ISSUER)
    r = RecoveryRequest(scope, HEAD)
    h = HistoryEvidence(r, "scope-ref", "source-ref", "coverage-ref",
                        "original-work", ("original-work", "old-alias"), ())
    e = EnrollmentRecord(scope, "original-work", h.historical_work_ids, ISSUER, "ledger-ref")
    return b, r, h, e


def observe(b, r, h, e, *, transport=None, scope=lambda _: True, coverage=lambda _: True,
            reader=None, verifier=lambda *_: True, enrollment=None):
    transport = transport or FakeTransport(b)
    return ForeignWorkAdmission(binding=b, transport=transport,
        history_reader=reader or (lambda _: h), verify_scope=scope, verify_coverage=coverage,
        read_enrollment=enrollment or (lambda _: e), verify_enrollment=verifier).observe(r)


def assert_no_authority(result):
    assert result.mutation_authorized is False
    assert result.controller_execution_approved is False


@pytest.mark.parametrize("repo,repo_id,issue_id", [
    ("example/moose", 10, 20), ("example/codeqa", 11, 21), ("example/sol", 12, 22),
])
def test_repository_neutral_existing_identity(repo, repo_id, issue_id):
    b, r, h, e = fixture(repo, repo_id, issue_id)
    transport = FakeTransport(b)
    got = observe(b, r, h, e, transport=transport)
    assert got.status is AdmissionStatus.EXISTING_ENROLLMENT_OBSERVED
    assert got.work_id == "original-work"
    assert got.recovery.historical_work_ids == h.historical_work_ids
    assert len(transport.reads) == 6
    assert_no_authority(got)


@pytest.mark.parametrize("wrong", ["repository", "issue", "pull_request", "head", "closed"])
def test_wrong_target_fails_before_history(wrong):
    b, r, h, e = fixture()
    transport = FakeTransport(b)
    def mutate(path, data):
        if wrong == "repository" and "full_name" in data:
            return dict(data, id=999)
        if "number" in data:
            if wrong == "issue": return dict(data, id=999)
            if wrong == "pull_request": return dict(data, pull_request={})
            if wrong == "closed": return dict(data, state="closed")
        if wrong == "head" and "object" in data:
            return dict(data, object={"type": "commit", "sha": "c" * 40})
        return data
    transport.mutate = mutate
    calls = []
    got = observe(b, r, h, e, transport=transport, reader=lambda q: calls.append(q))
    assert got.status is AdmissionStatus.TARGET_UNVERIFIED
    assert not calls and got.work_id is None
    assert_no_authority(got)


def test_known_blocker_dominates_incomplete_coverage_and_skips_enrollment():
    b, r, h, e = fixture()
    denial = HistoricalRecord("original-denial", "f" * 64, "TOOL_SAFETY")
    h = replace(h, coverage_ref=None, blockers=(denial,))
    calls = []
    got = observe(b, r, h, e, enrollment=lambda q: calls.append(q))
    assert got.status is AdmissionStatus.BLOCKER_PRESENT
    assert got.recovery.blockers == (denial,)
    assert not calls and got.work_id is None
    assert_no_authority(got)


@pytest.mark.parametrize("case,expected", [
    ("missing_coverage", AdmissionStatus.HISTORY_INCOMPLETE),
    ("unverified_scope", AdmissionStatus.IDENTITY_UNVERIFIED),
    ("unresolved_original", AdmissionStatus.IDENTITY_UNVERIFIED),
    ("derived_candidate", AdmissionStatus.ENROLLMENT_NOT_ATTESTED),
    ("missing_enrollment", AdmissionStatus.ENROLLMENT_NOT_ATTESTED),
    ("wrong_issuer", AdmissionStatus.ENROLLMENT_NOT_ATTESTED),
    ("wrong_work", AdmissionStatus.ENROLLMENT_NOT_ATTESTED),
    ("missing_alias", AdmissionStatus.ENROLLMENT_NOT_ATTESTED),
    ("wrong_enrollment_scope", AdmissionStatus.ENROLLMENT_NOT_ATTESTED),
    ("unverified_enrollment", AdmissionStatus.ENROLLMENT_NOT_ATTESTED),
    ("truthy_not_true", AdmissionStatus.ENROLLMENT_NOT_ATTESTED),
])
def test_no_false_admission(case, expected):
    b, r, h, e = fixture()
    kwargs = {}
    if case == "missing_coverage": kwargs["coverage"] = lambda _: False
    if case == "unverified_scope": kwargs["scope"] = lambda _: False
    if case in ("unresolved_original", "derived_candidate"):
        h = replace(h, original_work_id=None, historical_work_ids=(),
                    no_original_id_issued=case == "derived_candidate")
    if case == "missing_enrollment": e = None
    if case == "wrong_issuer": e = replace(e, issuer_id="other")
    if case == "wrong_work": e = replace(e, work_id="new", historical_work_ids=("new",))
    if case == "missing_alias": e = replace(e, historical_work_ids=(e.work_id,))
    if case == "wrong_enrollment_scope": e = replace(e, scope=replace(b.scope, issue_id=999))
    if case == "unverified_enrollment": kwargs["verifier"] = lambda *_: False
    if case == "truthy_not_true": kwargs["verifier"] = lambda *_: 1
    got = observe(b, r, h, e, **kwargs)
    assert got.status is expected and got.work_id is None
    assert_no_authority(got)


def test_target_head_moves_during_enrollment():
    b, r, h, e = fixture()
    transport = FakeTransport(b)
    def verify(*_):
        transport.head = "c" * 40
        return True
    got = observe(b, r, h, e, transport=transport, verifier=verify)
    assert got.status is AdmissionStatus.TARGET_UNVERIFIED
    assert got.work_id is None
    assert_no_authority(got)


def test_scope_cannot_change_by_new_issue_or_anchor():
    b, r, h, e = fixture()
    got = observe(b, replace(r, scope=replace(b.scope, work_anchor="new-id")), h, e)
    assert got.status is AdmissionStatus.TARGET_UNVERIFIED
    assert got.work_id is None


def test_transport_failure_fails_closed():
    b, r, h, e = fixture()
    transport = FakeTransport(b)
    def fail(*_): raise OSError("simulated outage")
    transport.mutate = fail
    got = observe(b, r, h, e, transport=transport)
    assert got.status is AdmissionStatus.TARGET_UNVERIFIED
    assert_no_authority(got)


def test_issuer_reader_exception_fails_closed():
    b, r, h, e = fixture()
    def fail(*_): raise OSError("simulated outage")
    got = observe(b, r, h, e, enrollment=fail)
    assert got.status is AdmissionStatus.ENROLLMENT_NOT_ATTESTED
    assert_no_authority(got)


@pytest.mark.parametrize("branch", ["../main", "refs//heads", "a b", "a.lock", "a@{b", "-x"])
def test_invalid_configured_ref(branch):
    b, *_ = fixture()
    with pytest.raises(ValueError): replace(b, target_branch=branch)
