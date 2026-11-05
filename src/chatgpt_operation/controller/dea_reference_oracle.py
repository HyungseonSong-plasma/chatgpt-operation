"""DEA documentation-reference oracle: independent, bounded, read-only evidence.

This module does NOT import codeQA's existing reference-audit implementation.
It observes a specified Markdown/link subset independently and records
unsupported syntax/remote consumer scope as UNKNOWN, never a universal PASS.
Source-object identity comes only from exact pinned Git blobs at the trusted runner.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha1, sha256
from html import unescape
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import subprocess
from typing import Any
from urllib.parse import unquote, urlsplit

_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_MD_LINK = re.compile(r"!?\[[^\]\n]*\]\((<[^>\n]*>|[^)\s\n]+)\)")
_REF_DEF = re.compile(r"^\s{0,3}\[([^\]\n]+)\]:\s*(<[^>\n]*>|\S+)")
_REF_USE = re.compile(r"(?<!!)\[[^\]\n]+\]\[([^\]\n]*)\]")
_HTML_LINK = re.compile(r"<(?:a|img)\s+[^>]*?(?:href|src)\s*=\s*['\"]([^'\"]+)['\"][^>]*>", re.I)
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_SETEXT = re.compile(r"^\s{0,3}(?:=+|-+)\s*$")
_HTML_ID = re.compile(r"<(?:a|div|span)\s+[^>]*?(?:id|name)\s*=\s*['\"]([^'\"]+)['\"]", re.I)
_LITERAL = re.compile(r"(?<![\w/])docs/[A-Za-z0-9_.\-/]+\.(?:md|json)\b")
_INLINE_CODE = re.compile(r"\x60+[^\x60\n]*\x60+")
_FENCE = re.compile(r"^\s{0,3}(\x60{3,}|~{3,})")
_SAFE_TEXT = frozenset({".md", ".py", ".json", ".yml", ".yaml", ".toml",
                        ".txt", ".sh", ".ini", ".cfg"})
_SCOPE = "dea.codeqa.document-reference.observation-subset.v0.1"
_MAX_SOURCE_BYTES = 4_000_000


class ReferenceOracleError(ValueError):
    """Immutable-source, malformed-input, or contract boundary failure."""


def _valid_path(path: str) -> bool:
    return (isinstance(path, str) and bool(path) and not path.startswith("/")
            and "\\" not in path and "\x00" not in path
            and all(p not in ("", ".", "..") for p in path.split("/"))
            and PurePosixPath(path).as_posix() == path)


def _blob_id(data: bytes) -> str:
    return sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def _filtered_lines(raw: str) -> list[str]:
    """Keep line positions stable; exclude fenced source samples."""
    lines, opened = [], ""
    for line in raw.splitlines():
        fence = _FENCE.match(line)
        if fence:
            token = fence.group(1)
            if not opened:
                opened = token
                lines.append("")
                continue
            if token[0] == opened[0] and len(token) >= len(opened):
                opened = ""
                lines.append("")
                continue
        lines.append("" if opened else line)
    if opened:
        # An unterminated fence is not safe to interpret as regular prose.
        raise ReferenceOracleError("unterminated Markdown fence")
    return lines


def _anchors(lines: list[str]) -> set[str]:
    result: set[str] = set()
    used: Counter[str] = Counter()
    for index, line in enumerate(lines):
        match = _HEADING.match(line)
        heading = match.group(1) if match else None
        if heading is None and index + 1 < len(lines) and _SETEXT.match(lines[index + 1]):
            heading = line.strip() or None
        if heading:
            heading = unescape(re.sub(r"<[^>]*>", "", heading))
            heading = _INLINE_CODE.sub(lambda m: m.group(0).strip(chr(96)), heading)
            slug = re.sub(r"[^\w\s-]", "", heading.lower())
            slug = re.sub(r"\s", "-", slug)
            suffix = used[slug]
            result.add(slug + ("-" + str(suffix) if suffix else ""))
            used[slug] += 1
        result.update(unescape(s) for s in _HTML_ID.findall(line))
    return result


def _make_record(source: str, line: int, kind: str, url: str,
                 all_paths: set[str], anchors: dict[str, set[str]]) -> dict[str, Any]:
    raw = unescape(url.strip("<>"))
    parts = urlsplit(raw)
    status = "LOCAL_RESOLVED"
    target = None
    fragment = unquote(parts.fragment) if parts.fragment else None
    if parts.scheme in ("http", "https", "mailto") or parts.netloc:
        status = "EXTERNAL_NOT_EVALUATED"
    elif parts.scheme or parts.path.startswith("/"):
        status = "UNSUPPORTED_URI"
    elif parts.path:
        destination = posixpath.normpath(posixpath.join(posixpath.dirname(source),
                                                        unquote(parts.path)))
        if destination == ".." or destination.startswith("../"):
            status = "ESCAPES_REPOSITORY"
        else:
            target = destination
    else:
        target = source if fragment else None
        if target is None:
            status = "UNSUPPORTED_URI"
    if target is not None:
        if target not in all_paths:
            status = "MISSING_LOCAL_TARGET"
        elif fragment and target.endswith(".md"):
            status = ("LOCAL_RESOLVED" if fragment in anchors.get(target, set())
                      else "FRAGMENT_NOT_EVALUATED")
    return {"source": source, "line": line, "kind": kind,
            "raw_target": raw, "resolved_target": target,
            "fragment": fragment, "status": status}


def _scan_markdown(path: str, raw: str, all_paths: set[str],
                   anchors: dict[str, set[str]]) -> list[dict[str, Any]]:
    lines = _filtered_lines(raw)
    definitions: dict[str, str] = {}
    for line in lines:
        match = _REF_DEF.match(line)
        if match:
            label = match.group(1).strip().casefold()
            value = match.group(2).strip("<>")
            if label in definitions and definitions[label] != value:
                raise ReferenceOracleError("ambiguous reference definition: " + label)
            definitions[label] = value
    records: list[dict[str, Any]] = []
    for lineno, line in enumerate(lines, 1):
        visible = _INLINE_CODE.sub("", line)
        for match in _MD_LINK.finditer(visible):
            records.append(_make_record(path, lineno, "markdown_inline", match.group(1),
                                        all_paths, anchors))
        for match in _HTML_LINK.finditer(visible):
            records.append(_make_record(path, lineno, "html_attribute", match.group(1),
                                        all_paths, anchors))
        for match in _REF_USE.finditer(visible):
            key = match.group(1).strip().casefold()
            if key in definitions:
                records.append(_make_record(path, lineno, "markdown_reference",
                                            definitions[key], all_paths, anchors))
            else:
                records.append({"source": path, "line": lineno,
                                "kind": "unresolved_reference", "raw_target": key,
                                "resolved_target": None, "fragment": None,
                                "status": "UNSUPPORTED_REFERENCE"})
        definition = _REF_DEF.match(visible)
        if definition:
            records.append(_make_record(path, lineno, "reference_definition",
                                        definition.group(2), all_paths, anchors))
        # This scanner deliberately does not pretend to parse the full
        # CommonMark grammar (nested inline destinations, multiline HTML).
        if ("](" in visible and not _MD_LINK.search(visible)) or re.search(
            r"\]\([^\n)]*\([^\n)]*\)[^\n)]*\)", visible
        ):
            records.append({"source": path, "line": lineno,
                            "kind": "unparsed_markdown", "raw_target": None,
                            "resolved_target": None, "fragment": None,
                            "status": "UNSUPPORTED_MARKDOWN_SYNTAX"})
    return records


def _observe_sources(files: dict[str, bytes], *, revision: str,
                     all_paths: set[str] | None,
                     origin: str) -> dict[str, Any]:
    """Internal scan; trusted origin is reserved for pinned Git-object readback."""
    if not _SHA40.fullmatch(revision):
        raise ReferenceOracleError("exact 40-character source commit required")
    if not isinstance(files, dict) or not files:
        raise ReferenceOracleError("empty selected source corpus")
    full_paths = set(files) if all_paths is None else set(all_paths)
    if not all(_valid_path(p) and isinstance(data, bytes) for p, data in files.items()):
        raise ReferenceOracleError("invalid source path or bytes")
    if not full_paths.issuperset(files) or not all(_valid_path(p) for p in full_paths):
        raise ReferenceOracleError("invalid/missing tracked-path denominator")
    decoded: dict[str, str] = {}
    for path, data in files.items():
        if len(data) > _MAX_SOURCE_BYTES:
            raise ReferenceOracleError("source exceeds bounded file size")
        try:
            decoded[path] = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ReferenceOracleError("unreadable selected text: " + path) from exc
    anchor_sets = {p: _anchors(_filtered_lines(s)) for p, s in decoded.items()
                   if p.endswith(".md")}
    records: list[dict[str, Any]] = []
    for path in sorted(decoded):
        text = decoded[path]
        if path.endswith(".md"):
            records.extend(_scan_markdown(path, text, full_paths, anchor_sets))
        if PurePosixPath(path).suffix.lower() in _SAFE_TEXT:
            for i, line in enumerate(text.splitlines(), 1):
                for match in _LITERAL.finditer(line):
                    target = match.group(0)
                    records.append({"source": path, "line": i,
                                    "kind": "text_docs_literal", "raw_target": target,
                                    "resolved_target": target, "fragment": None,
                                    "status": ("LITERAL_EXISTS_UNCLASSIFIED"
                                               if target in full_paths
                                               else "LITERAL_MISSING_UNCLASSIFIED")})
    records.sort(key=lambda x: (x["source"], x["line"], x["kind"],
                                x["raw_target"] or "", x["resolved_target"] or ""))
    catalog = [(p, _blob_id(data)) for p, data in sorted(files.items())]
    digest = sha256(json.dumps(catalog, separators=(",", ":")).encode()).hexdigest()
    counts = dict(sorted(Counter(r["status"] for r in records).items()))
    unknown = [r for r in records if r["status"] in {
        "UNSUPPORTED_URI", "UNSUPPORTED_REFERENCE", "UNSUPPORTED_MARKDOWN_SYNTAX",
        "FRAGMENT_NOT_EVALUATED"}]
    return {
        "schema_version": 1, "scope_id": _SCOPE, "source_revision": revision,
        "origin": origin, "selected_file_count": len(files),
        "tracked_path_count": len(full_paths), "selected_files_git_sha1": catalog,
        "corpus_digest_sha256": digest,
        "records": records, "status_counts": counts,
        "unsupported_syntax_count": len(unknown),
        "completeness": "BOUNDED_SUBSET_NOT_FULL_MARKDOWN",
        "external_consumer_coverage": "NOT_EVALUATED",
        "repository_mutation_authorized": False,
    }


def observe_sources(files: dict[str, bytes], *, revision: str,
                    all_paths: set[str] | None = None) -> dict[str, Any]:
    """Pure fixture analysis; caller-supplied bytes cannot attest their origin."""
    return _observe_sources(files, revision=revision, all_paths=all_paths,
                            origin="CALLER_SUPPLIED_UNATTESTED")


def compare_candidate(oracle: dict[str, Any],
                      submitted: dict[str, Any]) -> dict[str, Any]:
    """Compare candidate observations to an independently observed oracle.

    Equal observations establish bounded agreement only, never a champion.
    The oracle's origin must be an exact pinned Git readback, not model prose.
    """
    if oracle.get("origin") != "EXACT_GIT_OBJECT_READBACK":
        raise ReferenceOracleError("trusted pinned Git oracle required")
    for key in ("schema_version", "scope_id", "source_revision", "corpus_digest_sha256",
                "selected_file_count", "tracked_path_count"):
        if oracle.get(key) != submitted.get(key):
            raise ReferenceOracleError("incomparable candidate " + key)
    expected = oracle.get("records")
    actual = submitted.get("records")
    if not isinstance(expected, list) or not isinstance(actual, list):
        raise ReferenceOracleError("missing observation set")
    status = "PASS_BOUNDED" if expected == actual else "FAIL"
    if status == "PASS_BOUNDED" and oracle.get("unsupported_syntax_count", 0):
        status = "UNKNOWN"
    return {
        "status": status,
        "same_observation_denominator": len(expected) == len(actual),
        "oracle_record_count": len(expected),
        "candidate_record_count": len(actual),
        "scope_id": _SCOPE,
        "universal_semantic_equivalence": "NOT_PROVEN",
        "external_consumer_coverage": "NOT_EVALUATED",
        "champion": None,
        "repository_mutation_authorized": False,
    }


def _git(root: Path, *args: str) -> bytes:
    if args[0] not in ("rev-parse", "ls-tree", "cat-file"):
        raise ReferenceOracleError("only read-only git object commands permitted")
    try:
        proc = subprocess.run(["git", *args], cwd=root, capture_output=True,
                              check=False, timeout=90)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReferenceOracleError("Git object read unavailable") from exc
    if proc.returncode != 0:
        raise ReferenceOracleError("missing or incompatible pinned Git object")
    return proc.stdout


def scan_git_snapshot(root: Path, revision: str) -> dict[str, Any]:
    """Read every tracked path and selected relevant blobs at immutable SHA."""
    if not isinstance(revision, str) or not _SHA40.fullmatch(revision):
        raise ReferenceOracleError("exact source SHA required")
    root = Path(root).resolve()
    if not root.is_dir():
        raise ReferenceOracleError("Git repository missing")
    if _git(root, "rev-parse", revision + "^{commit}").decode("ascii").strip() != revision:
        raise ReferenceOracleError("Git revision does not resolve exactly")
    raw = _git(root, "ls-tree", "-rz", revision)
    selected: dict[str, bytes] = {}
    all_paths: set[str] = set()
    for item in raw.split(b"\0"):
        if not item:
            continue
        try:
            metadata, path_bytes = item.split(b"\t", 1)
            mode, kind, blob = metadata.decode("ascii").split(" ")
            path = path_bytes.decode("utf-8")
        except (ValueError, UnicodeError) as exc:
            raise ReferenceOracleError("invalid tracked path record") from exc
        if not _valid_path(path) or path in all_paths:
            raise ReferenceOracleError("unsafe/duplicate Git path")
        all_paths.add(path)
        if PurePosixPath(path).suffix.lower() not in _SAFE_TEXT:
            continue
        if kind != "blob" or mode not in ("100644", "100755") or not _SHA40.fullmatch(blob):
            raise ReferenceOracleError("unsupported selected Git object")
        data = _git(root, "cat-file", "blob", blob)
        if _blob_id(data) != blob:
            raise ReferenceOracleError("Git object/blob evidence mismatch")
        selected[path] = data
    return _observe_sources(selected, revision=revision, all_paths=all_paths,
                            origin="EXACT_GIT_OBJECT_READBACK")
