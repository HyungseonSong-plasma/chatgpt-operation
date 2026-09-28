"""Machine-readable scientific execution contract capability.

This module turns the repository's intent-preserving scientific-execution ontology
into a small declarative contract that can be validated and evaluated without
embedding physics-specific thresholds in the validator itself.

Ontology chain:
    CLAIM -> MODEL -> NUMERICAL REGIME -> FRAMEWORK-EFFECTIVE CONFIGURATION
          -> RUNTIME REGIME / TRAJECTORY -> OBSERVATION / EVIDENCE -> DECISION

The contract owns conformance mechanics only. Physical/model thresholds remain\nowned by the consumer scientific/model contract.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any, Callable


SCHEMA_VERSION = 1
PHASES = ("P1", "P3", "DECISION")
SEVERITIES = {"hard", "hold", "warn"}
DECISIONS = {"PENDING", "PASS", "FAIL", "HOLD", "REROUTE"}
_MISSING = object()


class ExecutionContractError(ValueError):
    """Raised when a machine-readable execution contract is malformed."""


def _require_type(value: Any, expected: type, path: str, noun: str) -> Any:
    if not isinstance(value, expected):
        raise ExecutionContractError(f"{path} must be {noun}")
    return value


def _mapping(value: Any, path: str) -> dict[str, Any]:
    return _require_type(value, dict, path, "an object")


def _list(value: Any, path: str) -> list[Any]:
    return _require_type(value, list, path, "an array")


def _string(mapping: dict[str, Any], key: str, path: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ExecutionContractError(f"{path}.{key} must be a non-empty string")
    return value.strip()


def _string_list(value: Any, path: str) -> list[str]:
    items = _list(value, path)
    if not all(isinstance(item, str) and item.strip() for item in items):
        raise ExecutionContractError(f"{path} must contain only non-empty strings")
    return [str(item).strip() for item in items]


def _lookup(root: dict[str, Any], dotted: str) -> Any:
    """Resolve the schema-v1 dotted path using the historical lookup semantics.

    List tokens intentionally retain Python integer-index semantics, including
    negative indices. Tightening that rule would be a schema semantic change and
    is deliberately outside this behavior-preserving refactor.
    """
    current: Any = root
    for token in dotted.split("."):
        if not token:
            raise KeyError(dotted)
        if isinstance(current, dict) and token in current:
            current = current[token]
            continue
        if isinstance(current, list):
            try:
                current = current[int(token)]
                continue
            except (ValueError, IndexError):
                pass
        raise KeyError(dotted)
    return current


@dataclass(frozen=True)
class CheckOperand:
    """Validated path or literal operand used by a contract check."""

    path: str | None = None
    value: Any = _MISSING

    def __post_init__(self) -> None:
        has_path = self.path is not None
        has_value = self.value is not _MISSING
        if has_path == has_value:
            raise ExecutionContractError(
                "CheckOperand must contain exactly one of 'path' or 'value'"
            )
        if has_path and (not isinstance(self.path, str) or not self.path.strip()):
            raise ExecutionContractError("CheckOperand.path must be a non-empty string")

    @classmethod
    def from_dict(cls, operand: dict[str, Any], path: str) -> "CheckOperand":
        item = _mapping(operand, path)
        has_path = "path" in item
        has_value = "value" in item
        if has_path == has_value:
            raise ExecutionContractError(
                f"{path} must contain exactly one of 'path' or 'value'"
            )
        if has_path:
            ref = item["path"]
            if not isinstance(ref, str) or not ref.strip():
                raise ExecutionContractError(f"{path}.path must be a non-empty string")
            return cls(path=ref.strip())
        return cls(value=item["value"])

    def resolve(self, root: dict[str, Any]) -> Any:
        if self.path is not None:
            return _lookup(root, self.path)
        return self.value


def _numeric(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"expected numeric value, got {type(value).__name__}")
    result = float(value)
    if not math.isfinite(result):
        raise TypeError("expected finite numeric value")
    return result


def _op_finite(left: Any, _right: Any | None) -> bool:
    try:
        if isinstance(left, list):
            return bool(left) and all(math.isfinite(_numeric(item)) for item in left)
        return math.isfinite(_numeric(left))
    except TypeError:
        return False


def _op_nonempty(left: Any, _right: Any | None) -> bool:
    try:
        return len(left) > 0
    except TypeError:
        return bool(left)


def _op_in(left: Any, right: Any | None) -> bool:
    try:
        return left in right
    except TypeError:
        return False


def _op_not_in(left: Any, right: Any | None) -> bool:
    try:
        return left not in right
    except TypeError:
        return False


def _numeric_compare(left: Any, right: Any | None, op: Callable[[float, float], bool]) -> bool:
    try:
        lhs = _numeric(left)
        rhs = _numeric(right)
    except TypeError:
        return False
    return op(lhs, rhs)


def _op_lt(left: Any, right: Any | None) -> bool:
    return _numeric_compare(left, right, lambda lhs, rhs: lhs < rhs)


def _op_le(left: Any, right: Any | None) -> bool:
    return _numeric_compare(left, right, lambda lhs, rhs: lhs <= rhs)


def _op_gt(left: Any, right: Any | None) -> bool:
    return _numeric_compare(left, right, lambda lhs, rhs: lhs > rhs)


def _op_ge(left: Any, right: Any | None) -> bool:
    return _numeric_compare(left, right, lambda lhs, rhs: lhs >= rhs)


Operator = Callable[[Any, Any | None], bool]
OPERATORS: dict[str, Operator] = {
    "eq": lambda left, right: left == right,
    "ne": lambda left, right: left != right,
    "lt": _op_lt,
    "le": _op_le,
    "gt": _op_gt,
    "ge": _op_ge,
    "finite": _op_finite,
    "nonempty": _op_nonempty,
    "in": _op_in,
    "not_in": _op_not_in,
}
OPS = set(OPERATORS)


def _evaluate_operator(op: str, left: Any, right: Any | None) -> bool:
    try:
        evaluator = OPERATORS[op]
    except KeyError as exc:
        raise ExecutionContractError(f"unsupported operator: {op}") from exc
    return evaluator(left, right)


def _validate_check(check: Any, index: int) -> dict[str, Any]:
    path = f"contract.checks[{index}]"
    item = _mapping(check, path)
    _string(item, "id", path)
    _string(item, "meaning", path)
    phase = _string(item, "phase", path)
    if phase not in PHASES:
        raise ExecutionContractError(f"{path}.phase must be one of {PHASES}")
    op = _string(item, "op", path)
    if op not in OPS:
        raise ExecutionContractError(f"{path}.op must be one of {sorted(OPS)}")
    severity = str(item.get("severity", "hard"))
    if severity not in SEVERITIES:
        raise ExecutionContractError(
            f"{path}.severity must be one of {sorted(SEVERITIES)}"
        )

    left = _mapping(item.get("left"), f"{path}.left")
    CheckOperand.from_dict(left, f"{path}.left")
    if op not in {"finite", "nonempty"}:
        right = _mapping(item.get("right"), f"{path}.right")
        CheckOperand.from_dict(right, f"{path}.right")
    elif "right" in item:
        raise ExecutionContractError(f"{path}.right is not used by operator {op}")

    on_fail = item.get("on_fail")
    if on_fail is not None and (not isinstance(on_fail, str) or not on_fail.strip()):
        raise ExecutionContractError(f"{path}.on_fail must be a non-empty string")
    return item


def validate_contract(data: dict[str, Any]) -> dict[str, Any]:
    """Validate ontology structure without requiring every runtime fact to exist yet."""
    root = _mapping(data, "contract")
    if root.get("schema_version") != SCHEMA_VERSION:
        raise ExecutionContractError(
            f"contract.schema_version must be {SCHEMA_VERSION}"
        )
    _string(root, "contract_id", "contract")

    claim = _mapping(root.get("claim"), "contract.claim")
    _string(claim, "statement", "contract.claim")
    _string(claim, "acceptance", "contract.claim")

    model = _mapping(root.get("model"), "contract.model")
    _string(model, "representation", "contract.model")
    _string_list(model.get("retained", []), "contract.model.retained")
    _string_list(model.get("reduced", []), "contract.model.reduced")
    _string_list(model.get("assumptions", []), "contract.model.assumptions")

    numerical = _mapping(root.get("numerical_regime"), "contract.numerical_regime")
    _string(numerical, "intent", "contract.numerical_regime")
    _mapping(
        numerical.get("declared_controls", {}),
        "contract.numerical_regime.declared_controls",
    )
    _mapping(
        numerical.get("declared_scales", {}),
        "contract.numerical_regime.declared_scales",
    )

    framework = _mapping(
        root.get("framework_effective"), "contract.framework_effective"
    )
    _string(framework, "provenance", "contract.framework_effective")
    _mapping(framework.get("controls", {}), "contract.framework_effective.controls")

    runtime = _mapping(root.get("runtime_regime"), "contract.runtime_regime")
    _mapping(runtime.get("observed", {}), "contract.runtime_regime.observed")

    evidence = _mapping(root.get("evidence"), "contract.evidence")
    requirements = _string_list(
        evidence.get("requirements", []), "contract.evidence.requirements"
    )
    if not requirements:
        raise ExecutionContractError(
            "contract.evidence.requirements must contain at least one requirement"
        )
    _mapping(evidence.get("observed", {}), "contract.evidence.observed")

    decision = _mapping(root.get("decision"), "contract.decision")
    status = _string(decision, "status", "contract.decision")
    if status not in DECISIONS:
        raise ExecutionContractError(
            f"contract.decision.status must be one of {sorted(DECISIONS)}"
        )

    checks = _list(root.get("checks"), "contract.checks")
    if not checks:
        raise ExecutionContractError("contract.checks must contain at least one check")
    seen: set[str] = set()
    for idx, raw in enumerate(checks):
        item = _validate_check(raw, idx)
        check_id = item["id"]
        if check_id in seen:
            raise ExecutionContractError(f"duplicate contract check id: {check_id}")
        seen.add(check_id)
    return root


def _iter_phases_through(phase: str) -> tuple[str, ...]:
    if phase not in PHASES:
        raise ExecutionContractError(f"phase must be one of {PHASES}")
    end = PHASES.index(phase)
    return PHASES[: end + 1]


def evaluate_contract(data: dict[str, Any], *, phase: str) -> dict[str, Any]:
    """Evaluate material ontology checks through ``phase`` and fail closed.

    Missing referenced facts are not silently ignored. They become UNRESOLVED and
    prevent a PASS for that phase. Warnings are preserved but do not block.
    """
    root = validate_contract(data)
    active_phases = set(_iter_phases_through(phase))
    results: list[dict[str, Any]] = []

    for check in root["checks"]:
        if check["phase"] not in active_phases:
            continue
        left_operand = CheckOperand.from_dict(
            check["left"], f"check {check['id']}.left"
        )
        raw_right = check.get("right")
        right_operand = (
            CheckOperand.from_dict(raw_right, f"check {check['id']}.right")
            if raw_right is not None
            else None
        )
        try:
            left = left_operand.resolve(root)
            right = right_operand.resolve(root) if right_operand is not None else None
        except KeyError as exc:
            results.append(
                {
                    "id": check["id"],
                    "phase": check["phase"],
                    "meaning": check["meaning"],
                    "severity": check.get("severity", "hard"),
                    "status": "UNRESOLVED",
                    "missing_path": str(exc.args[0]),
                    "on_fail": check.get("on_fail", "EXECUTION_CONTRACT_UNRESOLVED"),
                }
            )
            continue

        passed = _evaluate_operator(check["op"], left, right)
        results.append(
            {
                "id": check["id"],
                "phase": check["phase"],
                "meaning": check["meaning"],
                "severity": check.get("severity", "hard"),
                "status": "PASS" if passed else "FAIL",
                "left": left,
                "op": check["op"],
                "right": right,
                "on_fail": check.get("on_fail", "EXECUTION_CONTRACT_FAIL"),
            }
        )

    blockers = [
        item
        for item in results
        if item["severity"] in {"hard", "hold"}
        and item["status"] in {"FAIL", "UNRESOLVED"}
    ]
    warnings = [
        item
        for item in results
        if item["severity"] == "warn" and item["status"] != "PASS"
    ]

    requested_decision = root["decision"]["status"]
    ontology_pass = not blockers
    if phase == "DECISION" and requested_decision == "PASS" and not ontology_pass:
        status = "REJECTED_PASS"
    elif ontology_pass:
        status = "PASS"
    else:
        status = "HOLD"

    return {
        "schema_version": SCHEMA_VERSION,
        "contract_id": root["contract_id"],
        "phase": phase,
        "status": status,
        "ontology_conformant": ontology_pass,
        "requested_decision": requested_decision,
        "blockers": blockers,
        "warnings": warnings,
        "checks": results,
    }


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ExecutionContractError(f"failed to read contract {path}: {exc}") from exc
    return _mapping(value, "contract")


def _synthetic_contract() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "contract_id": "synthetic-fixed-step",
        "claim": {
            "statement": "exercise five intended physical timesteps",
            "acceptance": "five physical rows and preserved fixed-step semantics",
        },
        "model": {
            "representation": "synthetic transient",
            "retained": ["transient state"],
            "reduced": [],
            "assumptions": ["fixed-step semantics are part of the claim"],
        },
        "numerical_regime": {
            "intent": "fixed-step discriminator",
            "declared_controls": {
                "dt": 1.0e-13,
                "num_steps": 5,
                "end_time": 5.0e-13,
            },
            "declared_scales": {"tau": 1.0e-12},
        },
        "framework_effective": {
            "provenance": "synthetic executable introspection",
            "controls": {
                "dtmin": 1.0e-14,
                "timestep_tolerance": 1.0e-16,
                "adaptivity": False,
            },
        },
        "runtime_regime": {
            "observed": {
                "physical_rows": 5,
                "final_time": 5.0e-13,
                "actual_dt": 1.0e-13,
            }
        },
        "evidence": {
            "requirements": ["physical timestep rows", "final physical time"],
            "observed": {"checker_status": "PASS"},
        },
        "decision": {"status": "PASS"},
        "checks": [
            {
                "id": "dt-above-dtmin",
                "phase": "P1",
                "meaning": "requested dt must exceed effective dtmin",
                "left": {"path": "numerical_regime.declared_controls.dt"},
                "op": "gt",
                "right": {"path": "framework_effective.controls.dtmin"},
                "on_fail": "NUMERICAL_CONTRACT_FAIL",
            },
            {
                "id": "time-tolerance-below-dt",
                "phase": "P1",
                "meaning": "framework timestep tolerance must be below requested dt",
                "left": {"path": "framework_effective.controls.timestep_tolerance"},
                "op": "lt",
                "right": {"path": "numerical_regime.declared_controls.dt"},
                "on_fail": "NUMERICAL_CONTRACT_FAIL",
            },
            {
                "id": "physical-row-count",
                "phase": "P3",
                "meaning": "runtime must emit the intended number of physical rows",
                "left": {"path": "runtime_regime.observed.physical_rows"},
                "op": "ge",
                "right": {"path": "numerical_regime.declared_controls.num_steps"},
                "on_fail": "RUNTIME_SEMANTIC_FAIL",
            },
            {
                "id": "actual-fixed-dt",
                "phase": "P3",
                "meaning": "runtime must preserve the requested fixed timestep",
                "left": {"path": "runtime_regime.observed.actual_dt"},
                "op": "eq",
                "right": {"path": "numerical_regime.declared_controls.dt"},
                "on_fail": "RUNTIME_SEMANTIC_FAIL",
            },
            {
                "id": "evidence-checker",
                "phase": "DECISION",
                "meaning": "declared evidence checker must pass",
                "left": {"path": "evidence.observed.checker_status"},
                "op": "eq",
                "right": {"value": "PASS"},
                "on_fail": "EVIDENCE_CONTRACT_FAIL",
            },
        ],
    }


def _clone(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value))


def self_test() -> int:
    """Characterize schema-v1 behavior and the public evaluation report shape."""
    try:
        base = _synthetic_contract()
        result = evaluate_contract(base, phase="DECISION")
        if result["status"] != "PASS":
            raise AssertionError("positive ontology contract did not pass")
        if set(result) != {
            "schema_version",
            "contract_id",
            "phase",
            "status",
            "ontology_conformant",
            "requested_decision",
            "blockers",
            "warnings",
            "checks",
        }:
            raise AssertionError("evaluation report schema changed")

        expected_phase_counts = {"P1": 2, "P3": 4, "DECISION": 5}
        for phase, count in expected_phase_counts.items():
            if len(evaluate_contract(base, phase=phase)["checks"]) != count:
                raise AssertionError(f"phase accumulation changed for {phase}")

        bad_dt = _clone(base)
        bad_dt["framework_effective"]["controls"]["dtmin"] = 1.0e-12
        result = evaluate_contract(bad_dt, phase="P1")
        if result["status"] != "HOLD" or not result["blockers"]:
            raise AssertionError("dt/dtmin contradiction was not blocked")

        warning = _clone(bad_dt)
        warning["checks"][0]["severity"] = "warn"
        result = evaluate_contract(warning, phase="P1")
        if result["status"] != "PASS" or len(result["warnings"]) != 1:
            raise AssertionError("warning severity unexpectedly blocked the contract")

        hold = _clone(bad_dt)
        hold["checks"][0]["severity"] = "hold"
        result = evaluate_contract(hold, phase="P1")
        if result["status"] != "HOLD" or not result["blockers"]:
            raise AssertionError("hold severity did not block the contract")

        missing_runtime = _clone(base)
        del missing_runtime["runtime_regime"]["observed"]["physical_rows"]
        result = evaluate_contract(missing_runtime, phase="P3")
        if result["status"] != "HOLD" or not any(
            item["status"] == "UNRESOLVED" for item in result["blockers"]
        ):
            raise AssertionError("missing runtime evidence did not fail closed")

        missing_right = _clone(base)
        del missing_right["framework_effective"]["controls"]["dtmin"]
        result = evaluate_contract(missing_right, phase="P1")
        if result["status"] != "HOLD" or not any(
            item["status"] == "UNRESOLVED" for item in result["blockers"]
        ):
            raise AssertionError("missing right operand did not fail closed")

        bad_decision = _clone(base)
        bad_decision["evidence"]["observed"]["checker_status"] = "FAIL"
        result = evaluate_contract(bad_decision, phase="DECISION")
        if result["status"] != "REJECTED_PASS":
            raise AssertionError("invalid requested PASS was not rejected")

        duplicate = _clone(base)
        duplicate["checks"].append(dict(duplicate["checks"][0]))
        try:
            validate_contract(duplicate)
        except ExecutionContractError:
            pass
        else:
            raise AssertionError("duplicate check id was not rejected")

        for raw in ({}, {"path": "claim.statement", "value": "x"}):
            try:
                CheckOperand.from_dict(raw, "synthetic.operand")
            except ExecutionContractError:
                pass
            else:
                raise AssertionError("malformed operand was not rejected")
        if CheckOperand.from_dict({"value": None}, "literal").resolve(base) is not None:
            raise AssertionError("literal None operand semantics changed")

        lookup_fixture = {"items": ["first", "last"]}
        if _lookup(lookup_fixture, "items.0") != "first":
            raise AssertionError("positive list index lookup changed")
        if _lookup(lookup_fixture, "items.-1") != "last":
            raise AssertionError("schema-v1 negative list index semantics changed")
        try:
            _lookup(lookup_fixture, "items.9")
        except KeyError:
            pass
        else:
            raise AssertionError("out-of-range lookup did not fail")

        operator_cases = [
            ("eq", "x", "x", True),
            ("ne", "x", "y", True),
            ("lt", 1, 2, True),
            ("le", 2, 2, True),
            ("gt", 3, 2, True),
            ("ge", 2, 2, True),
            ("finite", [1.0, 2.0], None, True),
            ("nonempty", [1], None, True),
            ("in", "x", ["x", "y"], True),
            ("not_in", "z", ["x", "y"], True),
        ]
        for op, left, right, expected in operator_cases:
            if _evaluate_operator(op, left, right) is not expected:
                raise AssertionError(f"operator semantics changed for {op}")
        if _evaluate_operator("gt", True, 0):
            raise AssertionError("bool became numeric for ordered comparison")
        for nonfinite in (float("nan"), float("inf"), "1.0"):
            if _evaluate_operator("finite", nonfinite, None):
                raise AssertionError("finite operator accepted a non-finite/non-numeric value")
    except Exception as exc:
        print(f"EXECUTION_CONTRACT_SELFTEST: FAIL ({exc})")
        return 1
    print("EXECUTION_CONTRACT_SELFTEST: PASS")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate/evaluate a CORE-16 scientific execution contract"
    )
    parser.add_argument("contract", nargs="?", help="execution-contract JSON file")
    parser.add_argument(
        "--phase",
        choices=PHASES,
        default="DECISION",
        help="evaluate ontology checks through this phase",
    )
    parser.add_argument("--schema-only", action="store_true")
    parser.add_argument("--json-out")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()
    if not args.contract:
        parser.error("contract JSON path is required unless --self-test is used")

    path = Path(args.contract).expanduser().resolve()
    try:
        data = _load(path)
        if args.schema_only:
            root = validate_contract(data)
            result: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "contract_id": root["contract_id"],
                "status": "SCHEMA_PASS",
            }
        else:
            result = evaluate_contract(data, phase=args.phase)
    except ExecutionContractError as exc:
        result = {
            "schema_version": SCHEMA_VERSION,
            "status": "CONTRACT_INVALID",
            "error": str(exc),
        }

    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    print(text, end="")
    if args.json_out:
        Path(args.json_out).expanduser().resolve().write_text(text)
    return 0 if result.get("status") in {"SCHEMA_PASS", "PASS"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
