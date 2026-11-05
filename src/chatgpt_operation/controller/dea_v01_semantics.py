"""Finite-scope semantic observation comparison for DEA.

Never turn a passing CI suite or these supplied hashes into proof of universal
program equivalence. Origin verification belongs to a trusted runner.
"""
from __future__ import annotations

import re
from typing import Any

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_REQUIRED = frozenset({"return_value", "exceptions", "side_effects"})


class SemanticContractError(ValueError):
    pass


def _sha(v: Any) -> bool:
    return isinstance(v, str) and bool(_SHA.fullmatch(v))


def _cases(snapshot: Any, source: str) -> dict[str, dict[str, Any]]:
    if not isinstance(snapshot, dict) or snapshot.get("source_sha") != source:
        raise SemanticContractError("source identity mismatch")
    for field in ("oracle_sha", "input_set_sha", "environment_sha"):
        if not _sha(snapshot.get(field)):
            raise SemanticContractError("missing exact protocol " + field)
    capture = snapshot.get("captured_dimensions")
    if not isinstance(capture, list) or len(capture) != len(set(capture)) \
            or not _REQUIRED.issubset(capture):
        raise SemanticContractError("missing capture dimensions")
    rows = snapshot.get("cases")
    if not isinstance(rows, list) or not rows:
        raise SemanticContractError("empty behavior corpus")
    seen = {}
    for r in rows:
        if not isinstance(r, dict):
            raise SemanticContractError("invalid case")
        cid = r.get("case_id")
        if not isinstance(cid, str) or not cid.strip() or cid in seen:
            raise SemanticContractError("duplicate case")
        if not _sha(r.get("input_sha")):
            raise SemanticContractError("missing case input SHA")
        status = r.get("status")
        digest = r.get("observation_sha")
        if status not in ("OBSERVED", "UNKNOWN", "ERROR"):
            raise SemanticContractError("invalid case status")
        if status == "OBSERVED" and not _sha(digest):
            raise SemanticContractError("missing observed digest")
        if status != "OBSERVED" and digest is not None:
            raise SemanticContractError("unobserved case cannot claim output")
        seen[cid] = r
    return seen


def compare_observations(baseline: dict[str, Any], candidate: dict[str, Any],
                         *, base_sha: str, candidate_sha: str) -> dict[str, Any]:
    """Return PASS_BOUNDED, FAIL or UNKNOWN for a frozen finite case set."""
    if not _sha(base_sha) or not _sha(candidate_sha):
        raise SemanticContractError("exact source pins required")
    old = _cases(baseline, base_sha)
    new = _cases(candidate, candidate_sha)
    for field in ("oracle_sha", "input_set_sha", "environment_sha", "captured_dimensions"):
        if baseline[field] != candidate[field]:
            raise SemanticContractError("incomparable observation protocol: " + field)
    if set(old) != set(new):
        return _result("UNKNOWN", "changed case denominator", [], [])
    matched, different, unknown = [], [], []
    for cid in sorted(old):
        left, right = old[cid], new[cid]
        if left["input_sha"] != right["input_sha"]:
            raise SemanticContractError("case input changed: " + cid)
        if left["status"] != "OBSERVED" or right["status"] != "OBSERVED":
            unknown.append(cid)
        elif left["observation_sha"] != right["observation_sha"]:
            different.append(cid)
        else:
            matched.append(cid)
    if different:
        return _result("FAIL", "observable difference", matched, different, unknown)
    if unknown:
        return _result("UNKNOWN", "missing observations", matched, [], unknown)
    return _result("PASS_BOUNDED", "observations agree within frozen case set", matched, [])


def _result(status: str, reason: str, matches: list[str],
            differences: list[str], unknown: list[str] | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "matching_cases": matches,
        "differing_cases": differences,
        "unknown_cases": unknown or [],
        "source_provenance": "REQUIRES_INDEPENDENT_ATTESTATION",
        "external_consumers": "NOT_EVALUATED",
        "universal_semantic_equivalence": "NOT_PROVEN",
        "repository_mutation_authorized": False,
    }
