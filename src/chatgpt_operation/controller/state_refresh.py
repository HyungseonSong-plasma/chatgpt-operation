"""Deterministic delta fresh-read planning for scheduled work controllers."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


class StateRefreshError(ValueError):
    """Raised when state-refresh evidence is malformed."""


FULL_REFRESH_TRIGGERS = (
    ("present", False, "durable checkpoint is absent"),
    ("trustworthy", False, "durable checkpoint is not trustworthy"),
    ("phase_changed", True, "controller phase changed"),
    ("rule_revision_changed", True, "canonical rule revision changed"),
    ("scope_changed", True, "controller scope changed"),
    ("evidence_contradiction", True, "current evidence contradicts the checkpoint"),
    ("next_action_known", False, "next action cannot be established from the checkpoint"),
)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise StateRefreshError(f"{name} must be an object")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StateRefreshError(f"{name} must be a non-empty string")
    return value


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise StateRefreshError(f"{name} must be a boolean")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _strings(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise StateRefreshError(f"{name} must be an array")
    out: list[str] = []
    for index, item in enumerate(value):
        item = _text(item, f"{name}[{index}]")
        if item in out:
            raise StateRefreshError(f"{name} contains duplicate item {item!r}")
        out.append(item)
    return tuple(out)


def _append_unique(target: list[str], values: Sequence[str]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def _result(
    status: str,
    *,
    can_use_checkpoint: bool,
    next_action: str,
    reason: str,
    probe_reads: list[str] | None = None,
    expand_reads: list[str] | None = None,
    prewrite_reads: list[str] | None = None,
    skipped_surfaces: list[str] | None = None,
    changed_surfaces: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "can_use_checkpoint": can_use_checkpoint,
        "next_action": next_action,
        "reason": reason,
        "probe_reads": probe_reads or [],
        "expand_reads": expand_reads or [],
        "prewrite_reads": prewrite_reads or [],
        "skipped_surfaces": skipped_surfaces or [],
        "changed_surfaces": changed_surfaces or [],
    }


def evaluate(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Compute the minimum safe state-refresh read set for one controller decision."""

    data = _mapping(snapshot, "snapshot")
    if data.get("schema_version") != 1:
        raise StateRefreshError("schema_version must be 1")

    checkpoint = _mapping(data.get("checkpoint"), "checkpoint")
    for field, _, _ in FULL_REFRESH_TRIGGERS:
        _boolean(checkpoint.get(field), f"checkpoint.{field}")

    full_reasons = [
        reason
        for field, trigger_value, reason in FULL_REFRESH_TRIGGERS
        if checkpoint[field] is trigger_value
    ]
    if full_reasons:
        return _result(
            "FULL_REFRESH_REQUIRED",
            can_use_checkpoint=False,
            next_action="perform_full_refresh",
            reason="; ".join(full_reasons),
        )

    mutations_raw = data.get("planned_mutations", [])
    if not isinstance(mutations_raw, Sequence) or isinstance(mutations_raw, (str, bytes)):
        raise StateRefreshError("planned_mutations must be an array")
    mutation_targets: list[str] = []
    for index, value in enumerate(mutations_raw):
        target = _text(value, f"planned_mutations[{index}]")
        if target in mutation_targets:
            raise StateRefreshError(f"planned_mutations contains duplicate target {target!r}")
        mutation_targets.append(target)
    mutation_target_set = set(mutation_targets)

    surfaces_raw = data.get("surfaces")
    if not isinstance(surfaces_raw, Sequence) or isinstance(surfaces_raw, (str, bytes)):
        raise StateRefreshError("surfaces must be an array")

    surfaces: dict[str, dict[str, Any]] = {}
    ordered_ids: list[str] = []
    for index, raw in enumerate(surfaces_raw):
        surface = _mapping(raw, f"surfaces[{index}]")
        surface_id = _text(surface.get("id"), f"surfaces[{index}].id")
        if surface_id in surfaces:
            raise StateRefreshError(f"duplicate surface id {surface_id!r}")

        stability = _text(surface.get("stability"), f"surfaces[{index}].stability")
        if stability not in {"MUTABLE", "PINNED_IMMUTABLE"}:
            raise StateRefreshError(
                f"surfaces[{index}].stability must be MUTABLE or PINNED_IMMUTABLE"
            )
        locator_kind = _text(surface.get("locator_kind"), f"surfaces[{index}].locator_kind")
        if locator_kind not in {"FLOATING", "EXACT"}:
            raise StateRefreshError(
                f"surfaces[{index}].locator_kind must be FLOATING or EXACT"
            )
        decision_critical = _boolean(
            surface.get("decision_critical"), f"surfaces[{index}].decision_critical"
        )
        pin_verified = _boolean(
            surface.get("pin_verified"), f"surfaces[{index}].pin_verified"
        )
        probe_state = _text(surface.get("probe_state"), f"surfaces[{index}].probe_state")
        if probe_state not in {"NOT_RUN", "OK", "ERROR"}:
            raise StateRefreshError(
                f"surfaces[{index}].probe_state must be NOT_RUN, OK, or ERROR"
            )

        checkpoint_fingerprint = _optional_text(
            surface.get("checkpoint_fingerprint"),
            f"surfaces[{index}].checkpoint_fingerprint",
        )
        current_fingerprint = _optional_text(
            surface.get("current_fingerprint"),
            f"surfaces[{index}].current_fingerprint",
        )
        probe_reads = _strings(surface.get("probe_reads", []), f"surfaces[{index}].probe_reads")
        detail_reads = _strings(
            surface.get("detail_reads", []), f"surfaces[{index}].detail_reads"
        )
        prewrite_reads = _strings(
            surface.get("prewrite_reads", []), f"surfaces[{index}].prewrite_reads"
        )

        if stability == "PINNED_IMMUTABLE":
            if locator_kind != "EXACT":
                raise StateRefreshError(
                    f"pinned immutable surface {surface_id!r} must use locator_kind EXACT"
                )
            if checkpoint_fingerprint is None:
                raise StateRefreshError(
                    f"pinned immutable surface {surface_id!r} requires checkpoint_fingerprint"
                )
            if surface_id in mutation_target_set:
                raise StateRefreshError(
                    f"planned mutation cannot target pinned immutable surface {surface_id!r}"
                )
        elif pin_verified:
            raise StateRefreshError(
                f"mutable surface {surface_id!r} cannot declare pin_verified=true"
            )

        surfaces[surface_id] = {
            "stability": stability,
            "decision_critical": decision_critical,
            "pin_verified": pin_verified,
            "probe_state": probe_state,
            "checkpoint_fingerprint": checkpoint_fingerprint,
            "current_fingerprint": current_fingerprint,
            "probe_reads": probe_reads,
            "detail_reads": detail_reads,
            "prewrite_reads": prewrite_reads,
        }
        ordered_ids.append(surface_id)

    unknown_mutations = mutation_target_set - set(surfaces)
    if unknown_mutations:
        raise StateRefreshError(
            "planned_mutations reference unknown surfaces: "
            + ", ".join(sorted(unknown_mutations))
        )

    probe_reads: list[str] = []
    expand_reads: list[str] = []
    prewrite_reads: list[str] = []
    skipped_surfaces: list[str] = []
    changed_surfaces: list[str] = []
    blocked_surfaces: list[str] = []

    for surface_id in ordered_ids:
        surface = surfaces[surface_id]
        is_mutation_target = surface_id in mutation_target_set
        relevant = surface["decision_critical"] or is_mutation_target

        if surface["stability"] == "PINNED_IMMUTABLE" and surface["pin_verified"]:
            skipped_surfaces.append(surface_id)
            continue

        if not relevant:
            skipped_surfaces.append(surface_id)
            continue

        if surface["probe_state"] == "ERROR":
            blocked_surfaces.append(surface_id)
            continue

        if surface["probe_state"] == "NOT_RUN":
            if not surface["probe_reads"]:
                raise StateRefreshError(
                    f"surface {surface_id!r} needs a probe but probe_reads is empty"
                )
            _append_unique(probe_reads, surface["probe_reads"])
            continue

        # probe_state == OK
        if surface["current_fingerprint"] is None:
            raise StateRefreshError(
                f"surface {surface_id!r} has probe_state OK but no current_fingerprint"
            )

        if surface["current_fingerprint"] != surface["checkpoint_fingerprint"]:
            if not surface["detail_reads"]:
                raise StateRefreshError(
                    f"changed surface {surface_id!r} requires non-empty detail_reads"
                )
            changed_surfaces.append(surface_id)
            _append_unique(expand_reads, surface["detail_reads"])
        else:
            skipped_surfaces.append(surface_id)

    for surface_id in mutation_targets:
        surface = surfaces[surface_id]
        if surface["stability"] != "MUTABLE":
            raise StateRefreshError(
                f"planned mutation target {surface_id!r} must be MUTABLE"
            )
        if not surface["prewrite_reads"]:
            raise StateRefreshError(
                f"planned mutation target {surface_id!r} requires authoritative prewrite_reads"
            )
        _append_unique(prewrite_reads, surface["prewrite_reads"])

    if blocked_surfaces:
        return _result(
            "PROBE_BLOCKED",
            can_use_checkpoint=True,
            next_action="repair_probe_or_hold",
            reason="decision-critical probe failed for: " + ", ".join(blocked_surfaces),
            probe_reads=probe_reads,
            expand_reads=expand_reads,
            prewrite_reads=prewrite_reads,
            skipped_surfaces=skipped_surfaces,
            changed_surfaces=changed_surfaces,
        )

    if probe_reads:
        return _result(
            "PROBE_REQUIRED",
            can_use_checkpoint=True,
            next_action="execute_probe_reads_then_re_evaluate",
            reason="current fingerprints are missing for decision-critical mutable surfaces",
            probe_reads=probe_reads,
            expand_reads=expand_reads,
            prewrite_reads=prewrite_reads,
            skipped_surfaces=skipped_surfaces,
            changed_surfaces=changed_surfaces,
        )

    if expand_reads:
        return _result(
            "DELTA_REFRESH",
            can_use_checkpoint=True,
            next_action="execute_changed_surface_reads",
            reason="one or more mutable fingerprints changed since the checkpoint",
            expand_reads=expand_reads,
            prewrite_reads=prewrite_reads,
            skipped_surfaces=skipped_surfaces,
            changed_surfaces=changed_surfaces,
        )

    if prewrite_reads:
        return _result(
            "PREWRITE_ONLY",
            can_use_checkpoint=True,
            next_action="perform_authoritative_prewrite_reads",
            reason="checkpoint is current; only mutation-target authoritative reads remain",
            prewrite_reads=prewrite_reads,
            skipped_surfaces=skipped_surfaces,
        )

    return _result(
        "CHECKPOINT_CURRENT",
        can_use_checkpoint=True,
        next_action="continue_from_checkpoint",
        reason="all decision-critical mutable fingerprints are unchanged",
        skipped_surfaces=skipped_surfaces,
    )


def self_test() -> int:
    """Run minimal invariants for deterministic state refresh."""
    base = {
        "schema_version": 1,
        "checkpoint": {
            "present": True,
            "trustworthy": True,
            "phase_changed": False,
            "rule_revision_changed": False,
            "scope_changed": False,
            "evidence_contradiction": False,
            "next_action_known": True,
        },
        "surfaces": [
            {
                "id": "active_pr",
                "stability": "MUTABLE",
                "locator_kind": "FLOATING",
                "decision_critical": True,
                "pin_verified": False,
                "checkpoint_fingerprint": "head:a",
                "current_fingerprint": None,
                "probe_state": "NOT_RUN",
                "probe_reads": ["pr.identity"],
                "detail_reads": ["pr.reviews", "ci.exact_head"],
                "prewrite_reads": ["pr.authoritative"],
            },
            {
                "id": "sol_pin",
                "stability": "PINNED_IMMUTABLE",
                "locator_kind": "EXACT",
                "decision_critical": True,
                "pin_verified": True,
                "checkpoint_fingerprint": "sha:abc",
                "current_fingerprint": None,
                "probe_state": "NOT_RUN",
                "probe_reads": ["sol.commit"],
                "detail_reads": ["sol.runtime"],
                "prewrite_reads": [],
            },
        ],
        "planned_mutations": [],
    }

    first = evaluate(base)
    if first["status"] != "PROBE_REQUIRED" or first["probe_reads"] != ["pr.identity"]:
        raise StateRefreshError("self-test failed minimal probe planning")

    probed = dict(base)
    probed["surfaces"] = [dict(surface) for surface in base["surfaces"]]
    probed["surfaces"][0]["probe_state"] = "OK"
    probed["surfaces"][0]["current_fingerprint"] = "head:b"
    changed = evaluate(probed)
    if changed["status"] != "DELTA_REFRESH":
        raise StateRefreshError("self-test failed delta expansion")

    probed["surfaces"][0]["current_fingerprint"] = "head:a"
    probed["planned_mutations"] = ["active_pr"]
    prewrite = evaluate(probed)
    if prewrite["status"] != "PREWRITE_ONLY":
        raise StateRefreshError("self-test failed authoritative prewrite planning")
    if prewrite["prewrite_reads"] != ["pr.authoritative"]:
        raise StateRefreshError("self-test omitted authoritative prewrite read")

    return 0
