"""Validation for isolated multi-hypothesis scientific discriminator plans."""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

_SHA = re.compile(r"^[0-9a-f]{40}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class ScientificDiscriminatorError(ValueError):
    pass


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ScientificDiscriminatorError(f"{field} must be a non-empty string")
    return value.strip()


def _id(value: Any, field: str) -> str:
    value = _nonempty(value, field)
    if not _ID.fullmatch(value):
        raise ScientificDiscriminatorError(f"{field} is invalid")
    return value


def _string_list(value: Any, field: str, *, min_items: int = 1) -> list[str]:
    if not isinstance(value, list) or len(value) < min_items:
        raise ScientificDiscriminatorError(f"{field} must contain at least {min_items} item(s)")
    result = [_nonempty(item, f"{field}[{index}]") for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        raise ScientificDiscriminatorError(f"{field} items must be unique")
    return result


def _relative_namespace(value: Any, field: str) -> str:
    value = _nonempty(value, field)
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ScientificDiscriminatorError(
            f"{field} must be a relative namespace without '..'"
        )
    return value.rstrip("/")


def load_plan(path: str | Path) -> dict[str, Any]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise ScientificDiscriminatorError(f"invalid discriminator JSON: {exc}") from exc
    return validate_plan(raw)


def validate_plan(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ScientificDiscriminatorError("plan must be an object")
    allowed = {
        "schema_version", "cycle_id", "baseline_sha", "baseline_evidence",
        "objective", "frozen_invariants", "shared_inputs", "hypotheses", "experiments",
    }
    extra = set(raw) - allowed
    if extra:
        raise ScientificDiscriminatorError(f"plan: unknown fields {sorted(extra)}")
    if raw.get("schema_version") != 1:
        raise ScientificDiscriminatorError("schema_version must be 1")

    cycle_id = _id(raw.get("cycle_id"), "cycle_id")
    baseline_sha = _nonempty(raw.get("baseline_sha"), "baseline_sha").lower()
    if not _SHA.fullmatch(baseline_sha):
        raise ScientificDiscriminatorError("baseline_sha must be a lowercase 40-hex git SHA")
    baseline_evidence = _string_list(raw.get("baseline_evidence"), "baseline_evidence")

    objective = raw.get("objective")
    if not isinstance(objective, dict):
        raise ScientificDiscriminatorError("objective must be an object")
    obj_allowed = {"architecture_invariant", "metric", "target", "success_condition"}
    extra = set(objective) - obj_allowed
    if extra:
        raise ScientificDiscriminatorError(f"objective: unknown fields {sorted(extra)}")
    objective_norm = {
        "architecture_invariant": _nonempty(
            objective.get("architecture_invariant"), "objective.architecture_invariant"
        ),
        "metric": _nonempty(objective.get("metric"), "objective.metric"),
        "target": _nonempty(objective.get("target"), "objective.target"),
        "success_condition": _nonempty(
            objective.get("success_condition"), "objective.success_condition"
        ),
    }

    frozen = _string_list(raw.get("frozen_invariants"), "frozen_invariants")

    shared_inputs_raw = raw.get("shared_inputs", [])
    if not isinstance(shared_inputs_raw, list):
        raise ScientificDiscriminatorError("shared_inputs must be an array")
    shared_inputs: list[dict[str, str]] = []
    shared_ids: set[str] = set()
    for index, item in enumerate(shared_inputs_raw):
        where = f"shared_inputs[{index}]"
        if not isinstance(item, dict):
            raise ScientificDiscriminatorError(f"{where} must be an object")
        if set(item) - {"id", "evidence", "access"}:
            raise ScientificDiscriminatorError(f"{where} has unknown fields")
        item_id = _id(item.get("id"), f"{where}.id")
        if item_id in shared_ids:
            raise ScientificDiscriminatorError(f"duplicate shared input id: {item_id}")
        shared_ids.add(item_id)
        if item.get("access") != "read_only":
            raise ScientificDiscriminatorError(f"{where}.access must be read_only")
        shared_inputs.append({
            "id": item_id,
            "evidence": _nonempty(item.get("evidence"), f"{where}.evidence"),
            "access": "read_only",
        })

    hypotheses_raw = raw.get("hypotheses")
    if not isinstance(hypotheses_raw, list) or not (1 <= len(hypotheses_raw) <= 16):
        raise ScientificDiscriminatorError("hypotheses must contain 1..16 entries")
    hypotheses: list[dict[str, Any]] = []
    hypothesis_ids: set[str] = set()
    for index, item in enumerate(hypotheses_raw):
        where = f"hypotheses[{index}]"
        if not isinstance(item, dict):
            raise ScientificDiscriminatorError(f"{where} must be an object")
        allowed_h = {"id", "statement", "mechanism", "falsifier", "prior_evidence"}
        extra = set(item) - allowed_h
        if extra:
            raise ScientificDiscriminatorError(f"{where}: unknown fields {sorted(extra)}")
        hypothesis_id = _id(item.get("id"), f"{where}.id")
        if hypothesis_id in hypothesis_ids:
            raise ScientificDiscriminatorError(f"duplicate hypothesis id: {hypothesis_id}")
        hypothesis_ids.add(hypothesis_id)
        hypotheses.append({
            "id": hypothesis_id,
            "statement": _nonempty(item.get("statement"), f"{where}.statement"),
            "mechanism": _nonempty(item.get("mechanism"), f"{where}.mechanism"),
            "falsifier": _nonempty(item.get("falsifier"), f"{where}.falsifier"),
            "prior_evidence": _string_list(
                item.get("prior_evidence"), f"{where}.prior_evidence"
            ),
        })

    experiments_raw = raw.get("experiments")
    if not isinstance(experiments_raw, list) or not (1 <= len(experiments_raw) <= 32):
        raise ScientificDiscriminatorError("experiments must contain 1..32 entries")

    experiments: list[dict[str, Any]] = []
    experiment_ids: set[str] = set()
    lane_ids: set[str] = set()
    branches: set[str] = set()
    workspaces: set[str] = set()
    namespaces: set[str] = set()
    covered_hypotheses: set[str] = set()

    for index, item in enumerate(experiments_raw):
        where = f"experiments[{index}]"
        if not isinstance(item, dict):
            raise ScientificDiscriminatorError(f"{where} must be an object")
        allowed_e = {
            "id", "hypothesis_id", "lane_id", "base_sha", "branch", "workspace",
            "artifact_namespace", "shared_input_ids", "mutation_scope",
            "discriminating_observables", "controls", "variants",
        }
        extra = set(item) - allowed_e
        if extra:
            raise ScientificDiscriminatorError(f"{where}: unknown fields {sorted(extra)}")

        exp_id = _id(item.get("id"), f"{where}.id")
        if exp_id in experiment_ids:
            raise ScientificDiscriminatorError(f"duplicate experiment id: {exp_id}")
        experiment_ids.add(exp_id)

        hypothesis_id = _id(item.get("hypothesis_id"), f"{where}.hypothesis_id")
        if hypothesis_id not in hypothesis_ids:
            raise ScientificDiscriminatorError(
                f"{where}.hypothesis_id does not name a declared hypothesis"
            )
        covered_hypotheses.add(hypothesis_id)

        lane_id = _id(item.get("lane_id"), f"{where}.lane_id")
        if lane_id in lane_ids:
            raise ScientificDiscriminatorError(f"lane_id must be unique: {lane_id}")
        lane_ids.add(lane_id)

        base_sha = _nonempty(item.get("base_sha"), f"{where}.base_sha").lower()
        if base_sha != baseline_sha:
            raise ScientificDiscriminatorError(
                f"{where}.base_sha must equal the immutable baseline_sha"
            )

        branch_name = _nonempty(item.get("branch"), f"{where}.branch")
        if branch_name in branches:
            raise ScientificDiscriminatorError(
                f"each experiment lane must use a unique branch: {branch_name}"
            )
        branches.add(branch_name)

        workspace = _relative_namespace(item.get("workspace"), f"{where}.workspace")
        if workspace in workspaces:
            raise ScientificDiscriminatorError(
                f"each experiment lane must use a unique workspace: {workspace}"
            )
        workspaces.add(workspace)

        namespace = _relative_namespace(
            item.get("artifact_namespace"), f"{where}.artifact_namespace"
        )
        if namespace in namespaces:
            raise ScientificDiscriminatorError(
                f"artifact_namespace must be unique across lanes: {namespace}"
            )
        for other in namespaces:
            left = PurePosixPath(namespace)
            right = PurePosixPath(other)
            if left in right.parents or right in left.parents:
                raise ScientificDiscriminatorError(
                    "artifact namespaces must not overlap across lanes"
                )
        namespaces.add(namespace)

        shared_ids_requested = item.get("shared_input_ids", [])
        if not isinstance(shared_ids_requested, list):
            raise ScientificDiscriminatorError(f"{where}.shared_input_ids must be an array")
        requested = [
            _id(value, f"{where}.shared_input_ids[{i}]")
            for i, value in enumerate(shared_ids_requested)
        ]
        if len(requested) != len(set(requested)):
            raise ScientificDiscriminatorError(
                f"{where}.shared_input_ids must be unique"
            )
        unknown_shared = set(requested) - shared_ids
        if unknown_shared:
            raise ScientificDiscriminatorError(
                f"{where} references unknown shared inputs: {sorted(unknown_shared)}"
            )

        mutation_scope = _string_list(
            item.get("mutation_scope"), f"{where}.mutation_scope"
        )
        observables = _string_list(
            item.get("discriminating_observables"),
            f"{where}.discriminating_observables",
        )
        controls = _string_list(item.get("controls"), f"{where}.controls")

        variants_raw = item.get("variants", [])
        if not isinstance(variants_raw, list):
            raise ScientificDiscriminatorError(f"{where}.variants must be an array")
        variants: list[dict[str, str]] = []
        variant_ids: set[str] = set()
        for variant_index, variant in enumerate(variants_raw):
            vwhere = f"{where}.variants[{variant_index}]"
            if not isinstance(variant, dict) or set(variant) != {"id", "change"}:
                raise ScientificDiscriminatorError(
                    f"{vwhere} must contain exactly id and change"
                )
            variant_id = _id(variant.get("id"), f"{vwhere}.id")
            if variant_id in variant_ids:
                raise ScientificDiscriminatorError(
                    f"{where}.variant ids must be unique"
                )
            variant_ids.add(variant_id)
            variants.append({
                "id": variant_id,
                "change": _nonempty(variant.get("change"), f"{vwhere}.change"),
            })

        experiments.append({
            "id": exp_id,
            "hypothesis_id": hypothesis_id,
            "lane_id": lane_id,
            "base_sha": base_sha,
            "branch": branch_name,
            "workspace": workspace,
            "artifact_namespace": namespace,
            "shared_input_ids": requested,
            "mutation_scope": mutation_scope,
            "discriminating_observables": observables,
            "controls": controls,
            "variants": variants,
        })

    uncovered = hypothesis_ids - covered_hypotheses
    if uncovered:
        raise ScientificDiscriminatorError(
            f"every hypothesis needs at least one isolated experiment lane: {sorted(uncovered)}"
        )

    return {
        "schema_version": 1,
        "cycle_id": cycle_id,
        "baseline_sha": baseline_sha,
        "baseline_evidence": baseline_evidence,
        "objective": objective_norm,
        "frozen_invariants": frozen,
        "shared_inputs": shared_inputs,
        "hypotheses": hypotheses,
        "experiments": experiments,
    }


def summary(plan: dict[str, Any]) -> dict[str, Any]:
    normalized = validate_plan(plan)
    return {
        "status": "PLAN_VALID",
        "cycle_id": normalized["cycle_id"],
        "baseline_sha": normalized["baseline_sha"],
        "hypothesis_count": len(normalized["hypotheses"]),
        "experiment_lane_count": len(normalized["experiments"]),
        "lanes": [
            {
                "id": item["lane_id"],
                "hypothesis_id": item["hypothesis_id"],
                "branch": item["branch"],
                "workspace": item["workspace"],
                "artifact_namespace": item["artifact_namespace"],
            }
            for item in normalized["experiments"]
        ],
    }
