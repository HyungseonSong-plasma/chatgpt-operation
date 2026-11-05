"""Read-only DEA vector fitness: hard constraints before Pareto comparison.

This is a metadata verifier, NOT a trusted source/CI attestation service.
No output authorizes a champion, GitHub write or David promotion.
"""
from __future__ import annotations

import math
import re
from typing import Any

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_STATES = frozenset({"PASS", "FAIL", "UNKNOWN"})


class FitnessContractError(ValueError):
    pass


def _check(ok: bool, why: str) -> None:
    if not ok:
        raise FitnessContractError(why)


def _sha(x: Any) -> bool:
    return isinstance(x, str) and bool(_SHA.fullmatch(x))


def _unique_names(xs: Any) -> bool:
    return (isinstance(xs, list) and bool(xs)
            and all(isinstance(x, str) and bool(x.strip()) for x in xs)
            and len(xs) == len(set(xs)))


def _receipt(r: Any, head: str, profile: dict, label: str) -> None:
    _check(isinstance(r, dict) and r.get("observed_head_sha") == head,
           label + ": exact HEAD mismatch")
    for field in ("analyzer_sha", "profile_sha", "oracle_sha", "measurement_set_sha"):
        _check(r.get(field) == profile[field], label + ": " + field + " mismatch")
    _check(isinstance(r.get("evidence_ref"), str) and bool(r["evidence_ref"].strip()),
           label + ": missing evidence reference")


def _dominates(a: dict[str, float], b: dict[str, float], directions: dict[str, str]) -> bool:
    return (all((a[k] <= b[k] if direction == "min" else a[k] >= b[k])
                for k, direction in directions.items())
            and any((a[k] < b[k] if direction == "min" else a[k] > b[k])
                    for k, direction in directions.items()))


def evaluate(manifest: dict[str, Any]) -> dict[str, Any]:
    """Metadata-only fitness review; no proof of independently verified receipts."""
    _check(isinstance(manifest, dict) and manifest.get("schema_version") == 1,
           "invalid versioned manifest")
    _check(isinstance(manifest.get("work_id"), str) and bool(manifest["work_id"].strip()),
           "work_id required")
    base = manifest.get("base_sha")
    _check(_sha(base), "exact common base required")
    profile = manifest.get("profile")
    _check(isinstance(profile, dict), "profile required")
    for field in ("analyzer_sha", "profile_sha", "oracle_sha", "measurement_set_sha"):
        _check(_sha(profile.get(field)), "exact " + field + " required")
    gates = profile.get("hard_gates")
    _check(_unique_names(gates) and "semantic_contract" in gates,
           "unique hard gates including semantic_contract required")
    metrics = profile.get("metrics")
    _check(isinstance(metrics, dict) and bool(metrics)
           and all(isinstance(k, str) and bool(k.strip()) and v in ("min", "max")
                   for k, v in metrics.items()), "metrics must have directions")
    candidates = manifest.get("candidates")
    _check(isinstance(candidates, list) and len(candidates) >= 2,
           "baseline and candidate required")
    ids = [c.get("id") for c in candidates if isinstance(c, dict)]
    _check(len(ids) == len(candidates) and _unique_names(ids), "duplicate/invalid ids")
    baseline_id = manifest.get("baseline_id")
    _check(baseline_id in ids, "baseline id required")
    baseline = candidates[ids.index(baseline_id)]
    _check(baseline.get("head_sha") == base and baseline.get("generation") == 0,
           "unchanged baseline required")
    reports: dict[str, Any] = {}
    eligible: dict[str, dict[str, float]] = {}
    for c in candidates:
        cid, head = c["id"], c.get("head_sha")
        _check(_sha(head) and c.get("base_sha") == base,
               cid + ": exact HEAD and common base required")
        _check(type(c.get("generation")) is int and c["generation"] >= 0,
               cid + ": invalid generation")
        evidence = c.get("evidence")
        _check(isinstance(evidence, dict), cid + ": evidence required")
        gate_evidence, measurements = evidence.get("hard_gates"), evidence.get("metrics")
        _check(isinstance(gate_evidence, dict) and set(gate_evidence) == set(gates),
               cid + ": hard gate coverage mismatch")
        _check(isinstance(measurements, dict) and set(measurements) == set(metrics),
               cid + ": metric coverage mismatch")
        statuses, values = {}, {}
        metric_unknown = False
        for key in gates:
            r = gate_evidence[key]
            _receipt(r, head, profile, cid + ": " + key)
            _check(r.get("status") in _STATES, cid + ": invalid gate status")
            statuses[key] = r["status"]
        for key in metrics:
            r = measurements[key]
            _receipt(r, head, profile, cid + ": " + key)
            value = r.get("value")
            if value is None:
                metric_unknown = True
            else:
                _check(type(value) in (float, int) and math.isfinite(value),
                       cid + ": non-finite/non-numeric metric")
                values[key] = float(value)
        if "FAIL" in statuses.values():
            state = "INFEASIBLE"
        elif "UNKNOWN" in statuses.values():
            state = "UNKNOWN_HARD_GATE"
        elif metric_unknown:
            state = "UNKNOWN_METRICS"
        else:
            state = "METADATA_ELIGIBLE_NOT_ATTESTED"
            eligible[cid] = values
        reports[cid] = {
            "state": state,
            "hard_gates": statuses,
            "metric_values": {key: measurements[key].get("value") for key in metrics},
        }
    survivors = sorted(
        cid for cid, vector in eligible.items()
        if not any(other != cid and _dominates(other_vector, vector, metrics)
                   for other, other_vector in eligible.items())
    )
    admissible = baseline_id in eligible
    return {
        "schema_version": 1,
        "work_id": manifest["work_id"],
        "common_base_sha": base,
        "baseline_id": baseline_id,
        "baseline_preserved": True,
        "baseline_metadata_eligible": admissible,
        "candidate_evaluations": reports,
        "pareto_review_set": survivors if admissible else [],
        "decision": "REVIEW_REQUIRED" if admissible and survivors else "INSUFFICIENT_EVIDENCE",
        "evidence_authentication": "NOT_ATTESTED_BY_THIS_MODULE",
        "champion": None,
        "champion_promoted": False,
        "repository_mutation_authorized": False,
    }
