"""GitHub-Issue-backed, append-only-by-protocol blocker event journal.

Journal entries are tamper-evident, not GitHub-immutable: authorized GitHub users
can edit/delete Issue comments. The journal therefore fails closed on malformed
chains and unexpected authors, but an independent trusted anchor is required to
detect a deleted trailing event. Never interpret this journal as write authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Protocol

from .blocker_triage import BlockerObservation, BlockerSource
from .blocker_resolution import ClearanceEvidence, ClearanceKind

MARKER = "<!-- samuel-blocker-journal-v1 -->\n"
ZERO = "0" * 64
MAX_PAGES = 100


class JournalError(RuntimeError):
    pass


class IssueTransport(Protocol):
    def get(self, path: str, *, query: dict[str, str] | None = None) -> Any: ...
    def request(self, method: str, path: str, *, payload: dict[str, Any] | None = None) -> Any: ...


@dataclass(frozen=True)
class JournalSnapshot:
    events: tuple[dict[str, Any], ...]
    tip: str
    last_comment_id: int

    def matching(self, logical_intent_id: str) -> tuple[dict[str, Any], ...]:
        return tuple(x for x in self.events if x["payload"]["intent"] == logical_intent_id)


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _event_hash(sequence: int, previous: str, payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical({
        "schema": 1, "sequence": sequence, "previous": previous, "payload": payload,
    }).encode("utf-8")).hexdigest()


def blocker_payload(blocker: BlockerObservation) -> dict[str, Any]:
    if not isinstance(blocker, BlockerObservation):
        raise JournalError("typed blocker required")
    return {
        "event": "BLOCKED", "intent": blocker.logical_intent_id,
        "source": blocker.source.value, "provider": blocker.provider,
        "evidence_ref": blocker.evidence_ref, "http_status": blocker.http_status,
    }


def clearance_payload(evidence: ClearanceEvidence) -> dict[str, Any]:
    if not isinstance(evidence, ClearanceEvidence):
        raise JournalError("typed clearance required")
    return {
        "event": "CLEARED", "intent": evidence.logical_intent_id,
        "blocker_evidence_ref": evidence.blocker_evidence_ref,
        "kind": evidence.kind.value, "head": evidence.verified_head_sha,
        "evidence_ref": evidence.evidence_ref,
    }


def _validate_payload(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise JournalError("event payload must be an object")
    kind = payload.get("event")
    try:
        if kind == "REGISTERED":
            if set(payload) != {"event", "intent", "head", "evidence_ref"}:
                raise ValueError("invalid registration keys")
            if (not isinstance(payload["intent"], str)
                or len(payload["intent"]) != 64
                or any(c not in "0123456789abcdef" for c in payload["intent"])
                or not isinstance(payload["head"], str)
                or len(payload["head"]) != 40
                or any(c not in "0123456789abcdef" for c in payload["head"])
                or not isinstance(payload["evidence_ref"], str)
                or not payload["evidence_ref"].strip()):
                raise ValueError("invalid trusted work enrollment identity")
        elif kind == "BLOCKED":
            if set(payload) != {"event", "intent", "source", "provider",
                                "evidence_ref", "http_status"}:
                raise ValueError("invalid blocker keys")
            BlockerObservation(
                BlockerSource(payload["source"]), payload["intent"],
                payload["provider"], payload["evidence_ref"], payload["http_status"],
            )
        elif kind == "CLEARED":
            if set(payload) != {"event", "intent", "blocker_evidence_ref",
                                "kind", "head", "evidence_ref"}:
                raise ValueError("invalid clearance keys")
            ClearanceEvidence(
                payload["intent"], payload["blocker_evidence_ref"],
                ClearanceKind(payload["kind"]), payload["head"], payload["evidence_ref"],
            )
        else:
            raise ValueError("unrecognized event type")
    except (KeyError, TypeError, ValueError) as exc:
        raise JournalError("invalid typed event") from exc


class GitHubIssueBlockerJournal:
    """Durable shared receipts in owner-designated Issue; no secrets stored.

    Transport must be trusted and bound to the journal repository. Only entries
    authored by the configured service actor can be accepted as trusted.
    Multiple writers require external serialization; conflicting writers fail
    closed on readback, not silently repaired. A new Issue cannot grant rights.
    """

    def __init__(self, transport: IssueTransport, *, issue_number: int,
                 trusted_actor: str):
        if type(issue_number) is not int or issue_number <= 0:
            raise JournalError("a fixed positive journal issue number is required")
        if not isinstance(trusted_actor, str) or not trusted_actor.strip():
            raise JournalError("trusted actor required from out-of-band config")
        self.transport, self.issue_number, self.trusted_actor = (
            transport, issue_number, trusted_actor,
        )

    @property
    def path(self) -> str:
        return "/issues/" + str(self.issue_number) + "/comments"

    def read(self) -> JournalSnapshot:
        previous, sequence, last_comment = ZERO, 0, 0
        events: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            try:
                batch = self.transport.get(
                    self.path, query={"per_page": "100", "page": str(page)}
                )
            except Exception as exc:
                raise JournalError("journal enumeration unavailable") from exc
            if not isinstance(batch, list):
                raise JournalError("journal enumeration response malformed")
            if len(batch) > 100:
                raise JournalError("journal page size invalid")
            for comment in batch:
                if not isinstance(comment, dict) or type(comment.get("id")) is not int:
                    raise JournalError("journal comment identity malformed")
                if comment["id"] <= last_comment:
                    raise JournalError("journal order or duplicates invalid")
                last_comment = comment["id"]
                body = comment.get("body")
                if not isinstance(body, str):
                    raise JournalError("journal comment text malformed")
                if not body.startswith(MARKER):
                    continue
                author = comment.get("user")
                if not isinstance(author, dict) or author.get("login") != self.trusted_actor:
                    raise JournalError("unexpected journal writer identity")
                try:
                    entry = json.loads(body[len(MARKER):])
                except ValueError as exc:
                    raise JournalError("invalid journal JSON") from exc
                if not isinstance(entry, dict) or set(entry) != {
                    "schema", "sequence", "previous", "payload", "hash",
                }:
                    raise JournalError("malformed journal record")
                _validate_payload(entry["payload"])
                if (type(entry["schema"]) is not int or entry["schema"] != 1
                        or type(entry["sequence"]) is not int
                        or entry["sequence"] != sequence + 1
                        or entry["previous"] != previous
                        or entry["hash"] != _event_hash(
                            entry["sequence"], entry["previous"], entry["payload"]
                        )):
                    raise JournalError("journal sequence or hash chain broken")
                if entry["payload"]["event"] == "REGISTERED":
                    if any(e["payload"]["event"] == "REGISTERED"
                           and e["payload"]["intent"] == entry["payload"]["intent"]
                           for e in events):
                        raise JournalError("duplicate work registration")
                if entry["payload"]["event"] == "CLEARED":
                    p = entry["payload"]
                    matching = [
                        e for e in events if e["payload"]["event"] == "BLOCKED"
                        and e["payload"]["intent"] == p["intent"]
                        and e["payload"]["evidence_ref"] == p["blocker_evidence_ref"]
                    ]
                    if len(matching) != 1:
                        raise JournalError("clearance references absent or ambiguous blocker")
                sequence += 1
                previous = entry["hash"]
                events.append(entry)
            if len(batch) < 100:
                return JournalSnapshot(tuple(events), previous, last_comment)
        raise JournalError("journal page limit reached without complete enumeration")

    def _append(self, payload: dict[str, Any]) -> JournalSnapshot:
        _validate_payload(payload)
        before = self.read()
        # No journal write on a duplicate logical event (caller may retry after
        # lost response). Identical content must have its old identity.
        if any(e["payload"] == payload for e in before.events):
            return before
        if payload["event"] == "CLEARED":
            if not any(e["payload"]["event"] == "BLOCKED"
                       and e["payload"]["intent"] == payload["intent"]
                       and e["payload"]["evidence_ref"] == payload["blocker_evidence_ref"]
                       for e in before.events):
                raise JournalError("clearance has no corresponding blocker")
        sequence = len(before.events) + 1
        entry = {
            "schema": 1, "sequence": sequence,
            "previous": before.tip, "payload": payload,
            "hash": _event_hash(sequence, before.tip, payload),
        }
        try:
            result = self.transport.request(
                "POST", self.path,
                payload={"body": MARKER + _canonical(entry)},
            )
        except Exception as exc:
            # Remote write may have succeeded; caller must read first before
            # any retry. A blind second POST could break the event chain.
            raise JournalError("journal append outcome unknown; read before retry") from exc
        if not isinstance(result, dict) or type(result.get("id")) is not int:
            raise JournalError("journal write receipt invalid")
        after = self.read()
        if (len(after.events) != sequence or after.tip != entry["hash"]
                or after.last_comment_id != result["id"]):
            raise JournalError("journal post-write verification failed")
        return after

    def register_work(self, *, logical_intent_id: str, exact_head_sha: str,
                      evidence_ref: str) -> JournalSnapshot:
        # Enrollment does not certify absence of prior denials: the owner must
        # migrate historical blockers before adopting the gate in production.
        payload = {"event": "REGISTERED", "intent": logical_intent_id,
                   "head": exact_head_sha, "evidence_ref": evidence_ref}
        snapshot = self.read()
        if any(e["payload"]["event"] == "REGISTERED"
               and e["payload"]["intent"] == logical_intent_id
               and e["payload"] != payload for e in snapshot.events):
            raise JournalError("registered work identity cannot be replaced")
        return self._append(payload)

    def record_blocker(self, blocker: BlockerObservation) -> JournalSnapshot:
        return self._append(blocker_payload(blocker))

    def record_clearance(self, proof: ClearanceEvidence) -> JournalSnapshot:
        # A record does NOT attest that the originating authority cleared it.
        # The common gate always re-verifies evidence using trusted callbacks.
        return self._append(clearance_payload(proof))
