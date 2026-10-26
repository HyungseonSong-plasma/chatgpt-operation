"""Deterministic Samuel skill-catalog validation and trigger resolution."""

from __future__ import annotations

from typing import Any


_SAMUEL_REQUIRED_INIT_SKILLS = (
    "session-bootstrap",
    "state-refresh",
    "problem-oriented-response",
)
_PROBLEM_RESPONSE_CONTRACT = "skills/problem-oriented-response/contract.json"


class SkillCatalogError(ValueError):
    """Raised when central skill-catalog evidence is malformed."""


def _require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise SkillCatalogError(f"{field} must be a non-empty string")
    return value


def validate_catalog(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(catalog, dict):
        raise SkillCatalogError("catalog must be an object")
    if catalog.get("schema_version") != 1:
        raise SkillCatalogError("schema_version must be 1")

    raw_skills = catalog.get("skills")
    if not isinstance(raw_skills, list) or not raw_skills:
        raise SkillCatalogError("skills must be a non-empty array")

    result: list[dict[str, Any]] = []
    names: set[str] = set()
    paths: set[str] = set()

    for index, raw in enumerate(raw_skills):
        if not isinstance(raw, dict):
            raise SkillCatalogError(f"skills[{index}] must be an object")

        name = _require_string(raw.get("name"), f"skills[{index}].name")
        path = _require_string(raw.get("path"), f"skills[{index}].path")
        if not path.startswith("skills/") or not path.endswith("/README.md"):
            raise SkillCatalogError(
                f"skills[{index}].path must be skills/<name>/README.md"
            )

        load_on = raw.get("load_on")
        if not isinstance(load_on, list) or not load_on:
            raise SkillCatalogError(
                f"skills[{index}].load_on must be a non-empty array"
            )
        triggers: list[str] = []
        for trigger_index, trigger in enumerate(load_on):
            trigger = _require_string(
                trigger, f"skills[{index}].load_on[{trigger_index}]"
            )
            if trigger != trigger.upper():
                raise SkillCatalogError(
                    f"skills[{index}].load_on triggers must be uppercase"
                )
            triggers.append(trigger)
        if len(triggers) != len(set(triggers)):
            raise SkillCatalogError(
                f"skills[{index}].load_on triggers must be unique"
            )

        activation = raw.get("activation")
        if activation not in {"init", "trigger", "init_or_trigger"}:
            raise SkillCatalogError(
                f"skills[{index}].activation is unsupported"
            )

        contract_path = raw.get("contract_path")
        if contract_path is not None:
            contract_path = _require_string(
                contract_path, f"skills[{index}].contract_path"
            )
            if (
                not contract_path.startswith(f"skills/{name}/")
                or not contract_path.endswith(".json")
            ):
                raise SkillCatalogError(
                    f"skills[{index}].contract_path must be a JSON file "
                    f"inside skills/{name}/"
                )

        if name in names:
            raise SkillCatalogError(f"duplicate skill name: {name}")
        if path in paths:
            raise SkillCatalogError(f"duplicate skill path: {path}")
        names.add(name)
        paths.add(path)

        skill = {
            "name": name,
            "path": path,
            "load_on": triggers,
            "activation": activation,
        }
        if contract_path is not None:
            skill["contract_path"] = contract_path
        result.append(skill)

    return result


def resolve_triggers(
    catalog: dict[str, Any], triggers: list[str]
) -> dict[str, Any]:
    skills = validate_catalog(catalog)
    if not isinstance(triggers, list):
        raise SkillCatalogError("triggers must be an array")

    normalized: list[str] = []
    for index, trigger in enumerate(triggers):
        trigger = _require_string(trigger, f"triggers[{index}]")
        if trigger != trigger.upper():
            raise SkillCatalogError("requested triggers must be uppercase")
        normalized.append(trigger)

    if len(normalized) != len(set(normalized)):
        raise SkillCatalogError("requested triggers must be unique")

    if "INIT" in normalized:
        by_name = {skill["name"]: skill for skill in skills}
        missing = [
            name
            for name in _SAMUEL_REQUIRED_INIT_SKILLS
            if name not in by_name or "INIT" not in by_name[name]["load_on"]
        ]
        if missing:
            raise SkillCatalogError(
                "Samuel INIT is missing mandatory skills: " + ", ".join(missing)
            )
        response_skill = by_name["problem-oriented-response"]
        if response_skill.get("contract_path") != _PROBLEM_RESPONSE_CONTRACT:
            raise SkillCatalogError(
                "Samuel INIT requires the canonical problem-oriented response contract"
            )

    selected = []
    for skill in skills:
        if not any(trigger in skill["load_on"] for trigger in normalized):
            continue
        item = {"name": skill["name"], "path": skill["path"]}
        if "contract_path" in skill:
            item["contract_path"] = skill["contract_path"]
        selected.append(item)
    unresolved = sorted(
        trigger
        for trigger in normalized
        if not any(trigger in skill["load_on"] for skill in skills)
    )

    return {
        "status": "RESOLVED" if not unresolved else "TRIGGER_UNRESOLVED",
        "triggers": normalized,
        "skills": selected,
        "unresolved_triggers": unresolved,
    }
