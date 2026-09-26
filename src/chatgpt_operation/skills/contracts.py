"""Executable Skill contracts and architecture-to-runtime traceability."""
from __future__ import annotations

from dataclasses import dataclass
import importlib
import json
from pathlib import Path
from typing import Any, Callable

from chatgpt_operation.controller.invariants import SkillEvidence


class SkillContractError(ValueError):
    pass


@dataclass(frozen=True)
class ContractBinding:
    name: str
    target: str

    def resolve(self) -> Callable[..., Any] | type:
        module_name, separator, attribute = self.target.partition(":")
        if not separator or not module_name or not attribute:
            raise SkillContractError(f"invalid contract target for {self.name}: {self.target}")
        module = importlib.import_module(module_name)
        try:
            resolved = getattr(module, attribute)
        except AttributeError as exc:
            raise SkillContractError(
                f"contract {self.name} target does not exist: {self.target}"
            ) from exc
        if not callable(resolved):
            raise SkillContractError(f"contract {self.name} target is not callable")
        return resolved


CAPABILITY_BINDINGS = {
    "GITHUB_WORKFLOW_DISPATCH": "github-native-dispatch",
}


@dataclass(frozen=True)
class CapabilityResolution:
    capability: str
    provider: str
    contract: str | None = None


def resolve_capability(
    capability: str, *, native_available: bool = False
) -> CapabilityResolution:
    """Resolve an OS capability without treating connector absence as a blocker.

    Native tool availability is an optimization. Repository-owned Skill
    contracts are the durable fallback and remain available across cold starts.
    """
    if native_available:
        return CapabilityResolution(capability=capability, provider="native")
    from chatgpt_operation.skills.capability_registry import (
        CapabilityRegistryError,
        resolve_providers,
    )
    try:
        providers = resolve_providers(capability)
    except CapabilityRegistryError as exc:
        raise SkillContractError(str(exc)) from exc
    provider = next((p for p in providers if p.kind in {"skill", "workflow"}), None)
    if provider is None:
        raise SkillContractError(f"no repository provider for capability: {capability}")
    if provider.contract:
        binding = CONTRACT_BINDINGS.get(provider.contract)
        if binding is None:
            raise SkillContractError(
                f"capability {capability} references unbound contract: {provider.contract}"
            )
        binding.resolve()
    return CapabilityResolution(
        capability=capability, provider=provider.kind, contract=provider.contract
    )


CONTRACT_BINDINGS = {
    "decision-registry": ContractBinding(
        "decision-registry", "chatgpt_operation.controller.decisions:DecisionRegistry"
    ),
    "implementation-state": ContractBinding(
        "implementation-state", "chatgpt_operation.controller.implementation:ImplementationState"
    ),
    "reasoning-envelope": ContractBinding(
        "reasoning-envelope", "chatgpt_operation.controller.envelope:build_reasoning_envelope"
    ),
    "decision-guard": ContractBinding(
        "decision-guard", "chatgpt_operation.controller.decisions:DecisionGuard"
    ),
    "github-native-dispatch": ContractBinding(
        "github-native-dispatch", "chatgpt_operation.github.native_orchestration:dispatch_native_plan"
    ),
}


def load_catalog(path: str | Path) -> dict[str, Any]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1 or not isinstance(raw.get("skills"), list):
        raise SkillContractError("invalid skill catalog")
    return raw


def validate_catalog(path: str | Path) -> dict[str, Any]:
    catalog = load_catalog(path)
    resolved: list[str] = []
    for skill in catalog["skills"]:
        if not isinstance(skill, dict) or not isinstance(skill.get("name"), str):
            raise SkillContractError("catalog skill entry is invalid")
        contracts = skill.get("contracts", [])
        if not isinstance(contracts, list):
            raise SkillContractError(f"skill {skill['name']} contracts must be a list")
        for name in contracts:
            if name not in CONTRACT_BINDINGS:
                raise SkillContractError(
                    f"skill {skill['name']} references unbound contract: {name}"
                )
            CONTRACT_BINDINGS[name].resolve()
            resolved.append(name)
    return {
        "status": "PASS",
        "resolved_contracts": sorted(set(resolved)),
        "resolved_count": len(set(resolved)),
    }


def invoke_contract(name: str, *args: Any, **kwargs: Any) -> tuple[Any, SkillEvidence]:
    """Invoke one bound contract and return typed auditable execution evidence."""
    binding = CONTRACT_BINDINGS.get(name)
    if binding is None:
        raise SkillContractError(f"unbound contract: {name}")
    target = binding.resolve()
    try:
        result = target(*args, **kwargs)
    except Exception:
        raise
    return result, SkillEvidence(
        contract=name,
        contract_loaded=True,
        contract_executed=True,
        contract_passed=True,
    )
