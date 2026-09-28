"""Fail-closed ownership transfer contracts for consumer scientific code.

The manifest records which solver-independent components have been promoted into
chatgpt-operation and when a consumer duplicate is safe to retire. Promotion does
not authorize deletion. Retirement becomes eligible only after an explicit
consumer cutover verification is recorded.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

SCHEMA_VERSION = 1
_SHA = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_COMPONENT_PHASES = {
    "centralized",
    "consumer_cutover",
    "retirement_ready",
    "retired",
}
_CONSUMER_STATUSES = {
    "pending_cutover",
    "cutover_verified",
    "retired",
}


class CentralizationManifestError(ValueError):
    pass


@dataclass(frozen=True)
class RetirementCandidate:
    component_id: str
    repository: str
    duplicate_paths: tuple[str, ...]
    canonical_paths: tuple[str, ...]


def _nonempty(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CentralizationManifestError(f"{where} must be a non-empty string")
    return value.strip()


def _repository(value: Any, where: str) -> str:
    value = _nonempty(value, where)
    if not _REPOSITORY.fullmatch(value):
        raise CentralizationManifestError(f"{where} must be owner/name")
    return value


def _paths(value: Any, where: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not allow_empty):
        noun = "an array" if allow_empty else "a non-empty array"
        raise CentralizationManifestError(f"{where} must be {noun}")
    result: list[str] = []
    for index, item in enumerate(value):
        path = _nonempty(item, f"{where}[{index}]")
        if path.startswith("/") or ".." in Path(path).parts:
            raise CentralizationManifestError(
                f"{where}[{index}] must be repository-relative without '..'"
            )
        result.append(path)
    if len(result) != len(set(result)):
        raise CentralizationManifestError(f"{where} contains duplicate paths")
    return tuple(result)


def validate_manifest(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CentralizationManifestError("manifest root must be an object")
    allowed = {
        "schema_version",
        "canonical_repository",
        "retirement_policy",
        "components",
    }
    extra = set(raw) - allowed
    if extra:
        raise CentralizationManifestError(
            "manifest has unknown fields: " + repr(sorted(extra))
        )
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise CentralizationManifestError(
            f"schema_version must be {SCHEMA_VERSION}"
        )
    canonical_repository = _repository(
        raw.get("canonical_repository"), "canonical_repository"
    )

    retirement_policy = raw.get("retirement_policy")
    if not isinstance(retirement_policy, dict):
        raise CentralizationManifestError("retirement_policy must be an object")
    required_policy_keys = {
        "require_exact_canonical_revision",
        "require_compatibility_verification",
        "require_consumer_ci_success",
        "require_no_remaining_local_imports",
        "delete_only_through_consumer_policy",
    }
    if set(retirement_policy) != required_policy_keys:
        raise CentralizationManifestError(
            "retirement_policy must contain exactly "
            + repr(sorted(required_policy_keys))
        )
    if not all(
        isinstance(retirement_policy[key], bool)
        for key in required_policy_keys
    ):
        raise CentralizationManifestError(
            "retirement_policy values must be booleans"
        )
    if not all(retirement_policy.values()):
        raise CentralizationManifestError(
            "all retirement safety gates must remain enabled"
        )

    components = raw.get("components")
    if not isinstance(components, list) or not components:
        raise CentralizationManifestError(
            "components must be a non-empty array"
        )

    normalized: list[dict[str, Any]] = []
    component_ids: set[str] = set()
    for index, item in enumerate(components):
        where = f"components[{index}]"
        if not isinstance(item, dict):
            raise CentralizationManifestError(f"{where} must be an object")
        required = {
            "id",
            "origin_repository",
            "origin_revision",
            "origin_paths",
            "canonical_paths",
            "phase",
            "consumers",
        }
        if set(item) != required:
            raise CentralizationManifestError(
                f"{where} must contain exactly {sorted(required)!r}"
            )
        component_id = _nonempty(item["id"], f"{where}.id")
        if component_id in component_ids:
            raise CentralizationManifestError(
                f"duplicate component id: {component_id}"
            )
        component_ids.add(component_id)
        origin_repository = _repository(
            item["origin_repository"], f"{where}.origin_repository"
        )
        origin_revision = _nonempty(
            item["origin_revision"], f"{where}.origin_revision"
        ).lower()
        if not _SHA.fullmatch(origin_revision):
            raise CentralizationManifestError(
                f"{where}.origin_revision must be lowercase 40-hex"
            )
        origin_paths = _paths(item["origin_paths"], f"{where}.origin_paths")
        canonical_paths = _paths(
            item["canonical_paths"], f"{where}.canonical_paths"
        )
        phase = _nonempty(item["phase"], f"{where}.phase")
        if phase not in _COMPONENT_PHASES:
            raise CentralizationManifestError(
                f"{where}.phase must be one of {sorted(_COMPONENT_PHASES)!r}"
            )

        consumers = item["consumers"]
        if not isinstance(consumers, list) or not consumers:
            raise CentralizationManifestError(
                f"{where}.consumers must be a non-empty array"
            )
        consumer_repositories: set[str] = set()
        normalized_consumers: list[dict[str, Any]] = []
        for consumer_index, consumer in enumerate(consumers):
            cwhere = f"{where}.consumers[{consumer_index}]"
            if not isinstance(consumer, dict):
                raise CentralizationManifestError(
                    f"{cwhere} must be an object"
                )
            required_consumer = {
                "repository",
                "duplicate_paths",
                "status",
                "canonical_revision",
                "verification",
            }
            if set(consumer) != required_consumer:
                raise CentralizationManifestError(
                    f"{cwhere} must contain exactly "
                    + repr(sorted(required_consumer))
                )
            consumer_repository = _repository(
                consumer["repository"], f"{cwhere}.repository"
            )
            if consumer_repository in consumer_repositories:
                raise CentralizationManifestError(
                    f"{where} has duplicate consumer repository "
                    f"{consumer_repository}"
                )
            consumer_repositories.add(consumer_repository)
            duplicate_paths = _paths(
                consumer["duplicate_paths"], f"{cwhere}.duplicate_paths"
            )
            status = _nonempty(consumer["status"], f"{cwhere}.status")
            if status not in _CONSUMER_STATUSES:
                raise CentralizationManifestError(
                    f"{cwhere}.status must be one of "
                    + repr(sorted(_CONSUMER_STATUSES))
                )
            canonical_revision = consumer["canonical_revision"]
            if canonical_revision is not None:
                canonical_revision = _nonempty(
                    canonical_revision, f"{cwhere}.canonical_revision"
                ).lower()
                if not _SHA.fullmatch(canonical_revision):
                    raise CentralizationManifestError(
                        f"{cwhere}.canonical_revision must be lowercase 40-hex"
                    )
            verification = consumer["verification"]
            if not isinstance(verification, dict):
                raise CentralizationManifestError(
                    f"{cwhere}.verification must be an object"
                )
            required_verification = {
                "compatibility_verified",
                "consumer_ci_success",
                "remaining_local_imports",
                "consumer_revision",
                "compatibility_pull_request",
            }
            if set(verification) != required_verification:
                raise CentralizationManifestError(
                    f"{cwhere}.verification must contain exactly "
                    + repr(sorted(required_verification))
                )
            compatibility_verified = verification["compatibility_verified"]
            consumer_ci_success = verification["consumer_ci_success"]
            remaining_local_imports = verification["remaining_local_imports"]
            consumer_revision = verification["consumer_revision"]
            compatibility_pull_request = verification["compatibility_pull_request"]
            if not isinstance(compatibility_verified, bool):
                raise CentralizationManifestError(
                    f"{cwhere}.verification.compatibility_verified must be bool"
                )
            if not isinstance(consumer_ci_success, bool):
                raise CentralizationManifestError(
                    f"{cwhere}.verification.consumer_ci_success must be bool"
                )
            if not isinstance(remaining_local_imports, int) or isinstance(
                remaining_local_imports, bool
            ) or remaining_local_imports < 0:
                raise CentralizationManifestError(
                    f"{cwhere}.verification.remaining_local_imports "
                    "must be a non-negative integer"
                )
            if consumer_revision is not None:
                consumer_revision = _nonempty(
                    consumer_revision,
                    f"{cwhere}.verification.consumer_revision",
                ).lower()
                if not _SHA.fullmatch(consumer_revision):
                    raise CentralizationManifestError(
                        f"{cwhere}.verification.consumer_revision "
                        "must be lowercase 40-hex"
                    )
            if compatibility_pull_request is not None and (
                not isinstance(compatibility_pull_request, int)
                or isinstance(compatibility_pull_request, bool)
                or compatibility_pull_request < 1
            ):
                raise CentralizationManifestError(
                    f"{cwhere}.verification.compatibility_pull_request "
                    "must be a positive integer"
                )
            if compatibility_verified:
                if consumer_revision is None or compatibility_pull_request is None:
                    raise CentralizationManifestError(
                        f"{cwhere} compatibility verification requires exact "
                        "consumer_revision and compatibility_pull_request"
                    )
            if status in {"cutover_verified", "retired"}:
                if canonical_revision is None:
                    raise CentralizationManifestError(
                        f"{cwhere} verified/retired consumer needs canonical_revision"
                    )
                if not compatibility_verified or not consumer_ci_success:
                    raise CentralizationManifestError(
                        f"{cwhere} verified/retired consumer needs successful "
                        "compatibility and CI verification"
                    )
                if remaining_local_imports != 0:
                    raise CentralizationManifestError(
                        f"{cwhere} verified/retired consumer must have zero "
                        "remaining local imports"
                    )
            if status == "retired" and phase != "retired":
                raise CentralizationManifestError(
                    f"{cwhere} cannot be retired before component phase is retired"
                )
            normalized_consumers.append(
                {
                    "repository": consumer_repository,
                    "duplicate_paths": list(duplicate_paths),
                    "status": status,
                    "canonical_revision": canonical_revision,
                    "verification": {
                        "compatibility_verified": compatibility_verified,
                        "consumer_ci_success": consumer_ci_success,
                        "remaining_local_imports": remaining_local_imports,
                        "consumer_revision": consumer_revision,
                        "compatibility_pull_request": compatibility_pull_request,
                    },
                }
            )

        normalized.append(
            {
                "id": component_id,
                "origin_repository": origin_repository,
                "origin_revision": origin_revision,
                "origin_paths": list(origin_paths),
                "canonical_paths": list(canonical_paths),
                "phase": phase,
                "consumers": normalized_consumers,
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "canonical_repository": canonical_repository,
        "retirement_policy": dict(retirement_policy),
        "components": normalized,
    }


def load_manifest(path: str | Path) -> dict[str, Any]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CentralizationManifestError(
            f"cannot load centralization manifest: {type(exc).__name__}"
        ) from exc
    return validate_manifest(raw)


def centralization_reasoning_contract(
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Expose ownership-transfer state to reasoning without granting deletion authority."""
    normalized=validate_manifest(manifest)
    return {
        "canonical_repository":normalized["canonical_repository"],
        "retirement_policy":dict(normalized["retirement_policy"]),
        "components":[
            {
                "id":component["id"],
                "phase":component["phase"],
                "canonical_paths":list(component["canonical_paths"]),
                "consumers":[
                    {
                        "repository":consumer["repository"],
                        "duplicate_paths":list(consumer["duplicate_paths"]),
                        "status":consumer["status"],
                        "canonical_revision":consumer["canonical_revision"],
                        "verification":dict(consumer["verification"]),
                    }
                    for consumer in component["consumers"]
                ],
            }
            for component in normalized["components"]
        ],
        "rule":(
            "Centralized ownership does not authorize consumer deletion. "
            "A duplicate may be retired only when component.phase=retirement_ready "
            "and that consumer has status=cutover_verified with an exact canonical "
            "revision, compatibility verification, successful consumer CI, and "
            "zero remaining local imports. Mutation must still pass the consumer "
            "repository policy."
        ),
    }


def retirement_candidates(
    manifest: dict[str, Any],
    *,
    repository: str,
) -> tuple[RetirementCandidate, ...]:
    """Return only components explicitly ready for safe consumer-side deletion."""
    normalized = validate_manifest(manifest)
    repository = _repository(repository, "repository")
    result: list[RetirementCandidate] = []
    for component in normalized["components"]:
        if component["phase"] != "retirement_ready":
            continue
        for consumer in component["consumers"]:
            if (
                consumer["repository"] == repository
                and consumer["status"] == "cutover_verified"
            ):
                result.append(
                    RetirementCandidate(
                        component_id=component["id"],
                        repository=repository,
                        duplicate_paths=tuple(consumer["duplicate_paths"]),
                        canonical_paths=tuple(component["canonical_paths"]),
                    )
                )
    return tuple(sorted(result, key=lambda item: item.component_id))


__all__ = [
    "CentralizationManifestError",
    "RetirementCandidate",
    "SCHEMA_VERSION",
    "centralization_reasoning_contract",
    "load_manifest",
    "retirement_candidates",
    "validate_manifest",
]
