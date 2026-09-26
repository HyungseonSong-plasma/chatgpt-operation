"""Authoritative repository-owned capability/provider registry."""
from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

class CapabilityRegistryError(ValueError):
    pass

@dataclass(frozen=True)
class RegisteredProvider:
    name: str
    kind: str
    priority: int
    contract: str | None = None
    workflow: str | None = None
    executor_workflow: str | None = None
    required_permissions: dict[str, str] | None = None

def load_registry(path: str | Path = "skills/capability-registry.json") -> dict[str, Any]:
    raw=json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1 or not isinstance(raw.get("capabilities"),dict):
        raise CapabilityRegistryError("invalid capability registry")
    return raw

def resolve_providers(capability: str, path: str | Path = "skills/capability-registry.json") -> tuple[RegisteredProvider,...]:
    entry=load_registry(path)["capabilities"].get(capability)
    if not isinstance(entry,dict):
        raise CapabilityRegistryError(f"unbound capability: {capability}")
    raw=entry.get("providers")
    if not isinstance(raw,list) or not raw:
        raise CapabilityRegistryError(f"capability has no providers: {capability}")
    providers=[]
    names=set()
    for item in raw:
        if not isinstance(item,dict) or not item.get("name") or not item.get("kind"):
            raise CapabilityRegistryError(f"invalid provider for {capability}")
        if item["name"] in names:
            raise CapabilityRegistryError(f"duplicate provider for {capability}: {item['name']}")
        names.add(item["name"])
        providers.append(RegisteredProvider(
            name=item["name"],kind=item["kind"],priority=int(item.get("priority",100)),
            contract=item.get("contract"),workflow=item.get("workflow"),
            executor_workflow=item.get("executor_workflow"),
            required_permissions=item.get("required_permissions"),
        ))
    return tuple(sorted(providers,key=lambda p:(p.priority,p.name)))

def validate_registry(path: str | Path = "skills/capability-registry.json", root: str | Path = ".") -> dict[str,Any]:
    from chatgpt_operation.skills.contracts import CONTRACT_BINDINGS
    root=Path(root); registry=load_registry(path); checked=[]
    for capability in registry["capabilities"]:
        providers=resolve_providers(capability,path)
        for provider in providers:
            if provider.contract:
                binding=CONTRACT_BINDINGS.get(provider.contract)
                if binding is None:
                    raise CapabilityRegistryError(f"{provider.name} references unbound contract: {provider.contract}")
                binding.resolve()
            for attr in ("workflow","executor_workflow"):
                workflow=getattr(provider,attr)
                if workflow and not (root/workflow).is_file():
                    raise CapabilityRegistryError(f"{provider.name} missing workflow: {workflow}")
            if provider.required_permissions and provider.executor_workflow:
                text=(root/provider.executor_workflow).read_text(encoding="utf-8")
                for key,value in provider.required_permissions.items():
                    if f"{key}: {value}" not in text:
                        raise CapabilityRegistryError(f"{provider.name} missing permission {key}: {value}")
            checked.append(f"{capability}:{provider.name}")
    return {"status":"PASS","checked":checked}
