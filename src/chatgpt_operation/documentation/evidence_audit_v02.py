"""Read-only, consumer-owned evidence audit v0.2 (experimental internal contract).

No GitHub/network reads, mutations, review impersonation or semantic certification.
The caller must supply independently obtained exact-SHA witness verification.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping

from .status_labels import AXES, STATUS_COLORS, LabelError

_SHA = re.compile(r"^[0-9a-f]{40}$")
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_POSITIVE = {"decision": {"ADOPTED"}, "implementation": {"IMPLEMENTED", "PARTIAL"},
             "review": {"REVIEWED"}}
_ALLOWED_KINDS = {"decision": {"ADR"}, "implementation": {"SOURCE", "TEST"},
                  "review": {"INDEPENDENT_REVIEW"}}


@dataclass(frozen=True)
class EvidenceAuditV02:
    declared: Mapping[str, str]
    verified: Mapping[str, str]
    issues: tuple[str, ...]
    revalidation_queue: tuple[str, ...]
    status: str
    snapshot_sha: str
    consumer_repository: str
    scope: str
    at_revisions: Mapping[str, str]


def audit_evidence_v02(
    *, declared: Mapping[str, str], snapshot_sha: str,
    consumer_repository: str, scope: str,
    at_revisions: Mapping[str, str],
    witnesses: Mapping[str, Mapping[str, str]],
    independently_verified: Mapping[str, bool],
) -> EvidenceAuditV02:
    """Evaluate three claims against caller-supplied scope-bound witnesses.

    Each witness: kind, repository, path, revision, scope, provenance.
    The caller binds every witness to consumer_repository and scope. The decision
    axis may refer to a historical at-revision ADR, whereas implementation and
    review evidence must bind to the current snapshot_sha. The caller must
    separately verify historical ancestry, contents and the attested reviewer.
    For review: reviewer (nonempty and distinct from provenance's claimant).
    independently_verified=True is a caller attestation, NOT independently
    authenticated proof of semantics, history or reviewer independence.
    """
    if not isinstance(snapshot_sha, str) or not _SHA.fullmatch(snapshot_sha):
        raise LabelError("snapshot_sha must be an exact lowercase commit SHA")
    if not isinstance(consumer_repository, str) or not _REPO.fullmatch(consumer_repository):
        raise LabelError("consumer_repository must be an exact owner/repo identifier")
    if not isinstance(scope, str) or not scope.strip() or scope != scope.strip():
        raise LabelError("scope must identify the expected bounded claim")
    if not isinstance(at_revisions, Mapping) or set(at_revisions) != set(AXES):
        raise LabelError("at_revisions must contain exactly the three axes")
    if any(not isinstance(at_revisions[axis], str)
           or not _SHA.fullmatch(at_revisions[axis]) for axis in AXES):
        raise LabelError("at_revisions must use exact lowercase commit SHAs")
    if any(at_revisions[axis] != snapshot_sha for axis in ("implementation", "review")):
        raise LabelError("implementation and review at_revisions must be current")
    if not isinstance(declared, Mapping) or set(declared) != set(AXES):
        raise LabelError("declared must contain exactly the three axes")
    if not isinstance(witnesses, Mapping) or not set(witnesses) <= set(AXES):
        raise LabelError("invalid witness axes")
    if not isinstance(independently_verified, Mapping) or not set(independently_verified) <= set(AXES):
        raise LabelError("invalid verification axes")
    for axis in AXES:
        if declared[axis] not in STATUS_COLORS[axis]:
            raise LabelError("unsupported declared status")
    verified = {axis: "NOT_EVALUATED" for axis in AXES}
    issues = []
    queue = []
    for axis in AXES:
        value = declared[axis]
        witness = witnesses.get(axis)
        if value not in _POSITIVE[axis]:
            if witness:
                issues.append(f"{axis}:WITNESS_WITHOUT_POSITIVE_CLAIM")
            continue
        if not isinstance(witness, Mapping):
            issues.append(f"{axis}:MISSING_EVIDENCE")
            queue.append(axis)
            continue
        fields = ("kind", "repository", "path", "revision", "scope", "provenance")
        if any(not isinstance(witness.get(k), str) or not witness[k].strip() for k in fields):
            issues.append(f"{axis}:INCOMPLETE_PROVENANCE")
            queue.append(axis)
            continue
        if witness["kind"] not in _ALLOWED_KINDS[axis]:
            issues.append(f"{axis}:WRONG_EVIDENCE_KIND")
            queue.append(axis)
            continue
        if not _SHA.fullmatch(witness["revision"]):
            issues.append(f"{axis}:INVALID_EVIDENCE_SHA")
            queue.append(axis)
            continue
        if witness["repository"] != consumer_repository:
            issues.append(f"{axis}:REPOSITORY_MISMATCH")
            queue.append(axis)
            continue
        if witness["scope"] != scope:
            issues.append(f"{axis}:SCOPE_MISMATCH")
            queue.append(axis)
            continue
        if witness["revision"] != at_revisions[axis]:
            issues.append(f"{axis}:STALE_EVIDENCE")
            queue.append(axis)
            continue
        if axis == "review" and (
            not isinstance(witness.get("reviewer"), str)
            or not witness["reviewer"].strip()
            or witness["reviewer"].strip().casefold() == witness["provenance"].strip().casefold()
        ):
            issues.append("review:INDEPENDENCE_NOT_ATTESTED")
            queue.append(axis)
            continue
        if independently_verified.get(axis) is not True:
            issues.append(f"{axis}:VERIFICATION_REQUIRED")
            queue.append(axis)
            continue
        # Exact SHA and external verification attestation are necessary but not
        # sufficient to certify semantics. This is an evidence-coverage result.
        verified[axis] = value
    return EvidenceAuditV02(
        declared=dict(declared), verified=verified, issues=tuple(issues),
        revalidation_queue=tuple(queue),
        status="EVIDENCE_COVERED" if not issues else "REVIEW_REQUIRED",
        snapshot_sha=snapshot_sha,
        consumer_repository=consumer_repository,
        scope=scope,
        at_revisions=dict(at_revisions),
    )
