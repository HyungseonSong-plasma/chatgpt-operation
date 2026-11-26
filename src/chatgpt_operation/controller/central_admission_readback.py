"""Read-only observation of Samuel's existing domestic admission ledger.

V1 is a local Issue queue, not a foreign-work enrollment registry. This adapter
provides negative/diagnostic evidence only and cannot authenticate or issue a
foreign Work ID, attest historical coverage, or grant execution authority.
Runtime supplies the fixed repository/issue/actor config and authenticated GET.
A bot login or ID alone is not evidence of a particular workflow's authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any, Protocol

from .foreign_work_admission import ForeignAdmissionBinding

MARKER = "<!-- samuel-work-admission -->"
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_WORK = re.compile(r"issue:([1-9][0-9]*)\Z")


class LedgerReadError(ValueError):
    pass


class LedgerTransport(Protocol):
    def get(self, path: str, *, query: dict[str, str] | None = None) -> Any: ...


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LedgerReadError(message)


def _positive(value: object) -> bool:
    return type(value) is int and value > 0


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate ledger key")
        result[key] = value
    return result


@dataclass(frozen=True)
class CentralLedgerConfig:
    repository: str
    repository_id: int
    issue_number: int
    issue_id: int
    actor_login: str
    actor_id: int
    ledger_comment_id: int
    max_pages: int = 20

    def __post_init__(self):
        _require(isinstance(self.repository, str) and bool(_REPO.fullmatch(self.repository)), "invalid central repository")
        _require(all(_positive(v) for v in (self.repository_id, self.issue_number, self.issue_id,
                                             self.actor_id, self.ledger_comment_id, self.max_pages)), "invalid fixed identity")
        _require(isinstance(self.actor_login, str) and bool(self.actor_login.strip()), "invalid actor")
        _require(self.max_pages <= 100, "invalid page limit")


@dataclass(frozen=True)
class DomesticEntry:
    work_id: str
    issue_number: int
    html_url: str
    status: str


@dataclass(frozen=True)
class LedgerObservation:
    repository: str
    issue_id: int
    comment_id: int
    actor_id: int
    comment_count: int
    body_sha256: str
    entries: tuple[DomesticEntry, ...]

    @property
    def foreign_enrollment_attested(self) -> bool:
        return False

    @property
    def mutation_authorized(self) -> bool:
        return False

    @property
    def controller_execution_approved(self) -> bool:
        return False


class CentralAdmissionReadback:
    """Read all pages twice and validate fixed source identities and V1 scope.

    This does not prove comment immutability or completeness of other ledgers.
    Never map `issue:888` in the central queue to consumer Issue #888.
    A foreign-shaped record or unknown schema requires a new reviewed contract,
    not permissive decoding or implicit issuer verification.
    """
    def __init__(self, config: CentralLedgerConfig, transport: LedgerTransport):
        _require(isinstance(config, CentralLedgerConfig), "trusted config required")
        _require(callable(getattr(transport, "get", None)), "trusted transport required")
        self._config = config
        self._transport = transport

    def _issue(self, path):
        cfg = self._config
        value = self._transport.get(path)
        _require(isinstance(value, dict) and type(value.get("id")) is int
                 and value["id"] == cfg.issue_id and type(value.get("number")) is int
                 and value["number"] == cfg.issue_number and "pull_request" not in value
                 and value.get("url") == "https://api.github.com" + path
                 and type(value.get("comments")) is int and value["comments"] >= 0,
                 "central ledger issue identity/count mismatch")
        return value

    def _collect(self):
        cfg = self._config
        root = "/repos/" + cfg.repository
        repo = self._transport.get(root)
        _require(isinstance(repo, dict) and type(repo.get("id")) is int
                 and repo["id"] == cfg.repository_id and repo.get("full_name") == cfg.repository,
                 "central repository identity mismatch")
        path = root + "/issues/" + str(cfg.issue_number)
        before = self._issue(path)
        rows = []
        previous_id = 0
        for page in range(1, cfg.max_pages + 1):
            batch = self._transport.get(path + "/comments", query={"per_page": "100", "page": str(page)})
            _require(isinstance(batch, list) and len(batch) <= 100, "invalid comment page")
            for row in batch:
                _require(isinstance(row, dict) and _positive(row.get("id"))
                         and row["id"] > previous_id and isinstance(row.get("body"), str),
                         "malformed, duplicated or unordered comment")
                previous_id = row["id"]
                rows.append(row)
            if len(batch) < 100:
                break
        else:
            raise LedgerReadError("comment pagination incomplete")
        after = self._issue(path)
        _require(before["comments"] == after["comments"] == len(rows), "comment count changed or incomplete")
        matches = [r for r in rows if MARKER in r["body"]]
        _require(len(matches) == 1, "ledger absent or ambiguous")
        row = matches[0]
        actor = row.get("user")
        _require(row["id"] == cfg.ledger_comment_id and isinstance(actor, dict)
                 and type(actor.get("id")) is int and actor["id"] == cfg.actor_id
                 and actor.get("login") == cfg.actor_login, "ledger author or comment identity mismatch")
        body = row["body"]
        prefix, suffix = MARKER + "\n~~~json\n", "\n~~~"
        _require(body.startswith(prefix) and body.endswith(suffix), "unexpected ledger envelope")
        try:
            data = json.loads(body[len(prefix):-len(suffix)], object_pairs_hook=_pairs)
        except (TypeError, ValueError) as exc:
            raise LedgerReadError("invalid ledger JSON") from exc
        _require(isinstance(data, dict) and set(data) == {"schema_version", "work"}
                 and type(data["schema_version"]) is int and data["schema_version"] == 1
                 and isinstance(data["work"], dict), "unrecognized domestic ledger schema")
        entries = []
        for key, item in sorted(data["work"].items()):
            m = _WORK.fullmatch(key)
            _require(m is not None and isinstance(item, dict), "unsupported work key")
            number = int(m.group(1))
            url = f"https://github.com/{cfg.repository}/issues/{number}"
            _require(item.get("work_id") == key and type(item.get("issue_number")) is int
                     and item["issue_number"] == number and item.get("html_url") == url
                     and isinstance(item.get("status"), str) and bool(item["status"].strip()),
                     "non-domestic or malformed work entry")
            entries.append(DomesticEntry(key, number, url, item["status"]))
        observation = LedgerObservation(cfg.repository, cfg.issue_id, row["id"], cfg.actor_id,
                                        len(rows), sha256(body.encode()).hexdigest(), tuple(entries))
        # Compare complete comment observations, not only the ledger body or count.
        fingerprint = sha256(json.dumps(rows, sort_keys=True, separators=(",", ":"),
                                       ensure_ascii=True, allow_nan=False).encode()).hexdigest()
        return observation, fingerprint

    def observe(self) -> LedgerObservation:
        try:
            first, second = self._collect(), self._collect()
            _require(first == second, "central ledger changed during observation")
            return first[0]
        except LedgerReadError:
            raise
        except Exception as exc:
            raise LedgerReadError("central ledger read unavailable") from exc

    def read_enrollment(self, binding: ForeignAdmissionBinding) -> None:
        """A5.2a port: validate the source, then refuse V1 as foreign enrollment.

        None is not proof of clean history or nonexistence of an original ID.
        An actual foreign enrollment reader and independent verifier remain
        required before the positive branch of ForeignWorkAdmission is usable.
        """
        _require(isinstance(binding, ForeignAdmissionBinding), "typed binding required")
        _require(binding.scope.repository != self._config.repository, "foreign scope required")
        self.observe()
        return None
