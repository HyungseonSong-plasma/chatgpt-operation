"""Bounded machine-check Gate 1; independent approval remains an external Gate 2.

This module checks exact caller-supplied Git blob bytes and two narrowly
specified static predicates. It does not access GitHub, authenticate the source,
prove runtime semantics, or accept an independent human review.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Mapping

from .status_labels import LabelError

_SHA = re.compile(r"^[0-9a-f]{40}$")
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
_KINDS = {"JSON_POINTER_EQUALS", "PYTHON_IMPORT_ABSENT", "PYTHON_PACKAGE_IMPORT_ABSENT"}


@dataclass(frozen=True)
class AutomatedGateV01:
    """A machine-check result only; no reviewer verdict or semantic PASS."""

    repository: str
    revision: str
    scope: str
    status: str
    check_results: Mapping[str, str]
    issues: tuple[str, ...]
    independent_approval: str = "REVIEW_REQUIRED"
    semantic_certification: str = "NOT_EVALUATED"


def _git_blob_sha(text: str) -> str:
    raw = text.encode("utf-8")
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + bytes([0]) + raw).hexdigest()


def _matches_predicate(
    kind: str, text: str, subject: str, expected: str, *, path: str = "",
) -> bool:
    if kind == "JSON_POINTER_EQUALS":
        if not subject.startswith("/") or not subject[1:]:
            raise ValueError("JSON_POINTER_MALFORMED")
        obj = json.loads(text)
        for part in subject[1:].split("/"):
            key = part.replace("~1", "/").replace("~0", "~")
            if not isinstance(obj, dict) or key not in obj:
                return False
            obj = obj[key]
        return isinstance(obj, str) and obj == expected
    if kind == "PYTHON_IMPORT_ABSENT":
        if not subject or subject.startswith(".") or subject.endswith("."):
            raise ValueError("MODULE_PREFIX_MALFORMED")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = (alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    # Relative imports are not resolved without package context.
                    raise ValueError("RELATIVE_IMPORT_UNSUPPORTED")
                modules = (node.module or "",)
            else:
                continue
            if any(m == subject or m.startswith(subject + ".") for m in modules):
                return False
        return True
    if kind == "PYTHON_PACKAGE_IMPORT_ABSENT":
        # Resolve relative imports against the package containing this module.
        # No import execution or dynamic-call approximation is attempted.
        prefix = "src/"
        if not path.startswith(prefix) or not path.endswith(".py"):
            raise ValueError("PACKAGE_PATH_UNSUPPORTED")
        module_parts = path[len(prefix):-3].split("/")
        if len(module_parts) < 2 or any(not part.isidentifier() for part in module_parts):
            raise ValueError("PACKAGE_PATH_UNSUPPORTED")
        package = module_parts[:-1] if module_parts[-1] != "__init__" else module_parts[:-1]
        if not subject or any(not part.isidentifier() for part in subject.split(".")):
            raise ValueError("MODULE_PREFIX_MALFORMED")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = (alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    drop = node.level - 1
                    if drop >= len(package):
                        raise ValueError("RELATIVE_IMPORT_ESCAPES_PACKAGE")
                    base = package[:len(package) - drop]
                    if node.module:
                        base += node.module.split(".")
                    absolute = ".".join(base)
                else:
                    absolute = node.module or ""
                names = (absolute,) + tuple(
                    absolute + "." + alias.name
                    for alias in node.names if alias.name != "*"
                )
                if any(alias.name == "*" for alias in node.names):
                    # Wildcard imports are not automatically safe for this narrow predicate.
                    raise ValueError("WILDCARD_IMPORT_UNSUPPORTED")
            else:
                continue
            if any(name == subject or name.startswith(subject + ".") for name in names):
                return False
        return True
    raise ValueError("UNSUPPORTED_PREDICATE")


def verify_automated_gate_v01(
    *, repository: str, revision: str, scope: str,
    required_checks: tuple[str, ...],
    checks: Mapping[str, Mapping[str, str]],
) -> AutomatedGateV01:
    """Fail closed on missing checks, changed blobs or unsupported predicates.

    Each check binds repository/revision/scope/path/blob_sha/content to a
    narrow static predicate: JSON_POINTER_EQUALS or PYTHON_IMPORT_ABSENT.
    Content is supplied by the caller; its external origin is NOT verified.
    """
    if not isinstance(repository, str) or not _REPO.fullmatch(repository):
        raise LabelError("repository must be owner/repo")
    if not isinstance(revision, str) or not _SHA.fullmatch(revision):
        raise LabelError("revision must be an exact lowercase commit SHA")
    if not isinstance(scope, str) or not scope.strip() or scope.strip() != scope:
        raise LabelError("scope must be a bounded identifier")
    if (not isinstance(required_checks, tuple) or not required_checks
            or any(not isinstance(x, str) or not _ID.fullmatch(x)
                   for x in required_checks)
            or len(set(required_checks)) != len(required_checks)):
        raise LabelError("required_checks must be nonempty unique identifiers")
    if not isinstance(checks, Mapping):
        raise LabelError("checks must be a mapping")

    outcomes: dict[str, str] = {}
    issues: list[str] = []
    extras = set(checks) - set(required_checks)
    if extras:
        issues.append("UNDECLARED_CHECK")
    for check_id in required_checks:
        c = checks.get(check_id)
        if not isinstance(c, Mapping):
            outcomes[check_id] = "NOT_EVALUATED"
            issues.append(f"{check_id}:MISSING_CHECK")
            continue
        fields = ("repository", "revision", "scope", "path",
                  "blob_sha", "content", "kind", "subject")
        if any(not isinstance(c.get(f), str) for f in fields):
            outcomes[check_id] = "FAIL"
            issues.append(f"{check_id}:INCOMPLETE_CHECK")
            continue
        if (c["repository"] != repository or c["revision"] != revision
                or c["scope"] != scope):
            outcomes[check_id] = "FAIL"
            issues.append(f"{check_id}:BOUNDARY_MISMATCH")
            continue
        path = c["path"]
        if (not path or path.startswith("/") or chr(92) in path or ":"
                in path or any(part in ("", ".", "..") for part in path.split("/"))):
            outcomes[check_id] = "FAIL"
            issues.append(f"{check_id}:UNSAFE_PATH")
            continue
        if not _SHA.fullmatch(c["blob_sha"]) or c["blob_sha"] != _git_blob_sha(c["content"]):
            outcomes[check_id] = "FAIL"
            issues.append(f"{check_id}:BLOB_MISMATCH")
            continue
        if c["kind"] not in _KINDS:
            outcomes[check_id] = "NOT_EVALUATED"
            issues.append(f"{check_id}:UNSUPPORTED_PREDICATE")
            continue
        if (c["kind"] == "JSON_POINTER_EQUALS" and not isinstance(c.get("expected"), str)):
            outcomes[check_id] = "FAIL"
            issues.append(f"{check_id}:MISSING_EXPECTED_VALUE")
            continue
        if c["kind"] in {"PYTHON_IMPORT_ABSENT", "PYTHON_PACKAGE_IMPORT_ABSENT"} and not path.endswith(".py"):
            outcomes[check_id] = "FAIL"
            issues.append(f"{check_id}:NOT_PYTHON_SOURCE")
            continue
        if c["kind"] == "JSON_POINTER_EQUALS" and not path.endswith(".json"):
            outcomes[check_id] = "FAIL"
            issues.append(f"{check_id}:NOT_JSON_SOURCE")
            continue
        try:
            accepted = _matches_predicate(
                c["kind"], c["content"], c["subject"], c.get("expected", ""),
                path=path)
        except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
            outcomes[check_id] = "FAIL"
            issues.append(f"{check_id}:UNVERIFIABLE_PREDICATE")
            continue
        outcomes[check_id] = "PASS" if accepted else "FAIL"
        if not accepted:
            issues.append(f"{check_id}:PREDICATE_FAILED")
    return AutomatedGateV01(
        repository=repository, revision=revision, scope=scope,
        status="SCOPED_CHECKS_PASS" if not issues else "REVIEW_REQUIRED",
        check_results=outcomes, issues=tuple(issues),
    )
