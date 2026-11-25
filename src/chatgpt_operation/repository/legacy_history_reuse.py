"""Optional read-only reuse of verified history within one trusted runtime.

The authoritative version probe must cover original enrollment, all aliases,
all denial/clearance sources and revocation of verification authority. GitHub
HEAD, time-to-live, local hashes, or a visible comments digest alone do not
satisfy this contract. No durable cache, provider execution or clearance.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re
from threading import RLock
from typing import Callable

from .legacy_work_identity import (HistoryEvidence, RecoveryRequest, RecoveryResult,
                                   RecoveryStatus, TrustedReader, TrustedVerifier)
from .legacy_mutation_preflight import HistoryPreflight, observe_history


def evidence_digest(evidence: HistoryEvidence) -> str:
    """Canonical digest binds every field, including aliases and original records."""
    return sha256(json.dumps(asdict(evidence), sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True, allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class HistoryVersion:
    request: RecoveryRequest
    authority_id: str
    central_revision: str
    generation: int
    digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.request, RecoveryRequest):
            raise ValueError("request binding required")
        if not isinstance(self.authority_id, str) or not self.authority_id.strip():
            raise ValueError("authority identity required")
        if not isinstance(self.central_revision, str) or not re.fullmatch(r"[0-9a-f]{40}", self.central_revision):
            raise ValueError("exact Samuel pin required")
        if type(self.generation) is not int or self.generation < 0:
            raise ValueError("nonnegative authoritative generation required")
        if not isinstance(self.digest, str) or not re.fullmatch(r"[0-9a-f]{64}", self.digest):
            raise ValueError("complete evidence digest required")


@dataclass(frozen=True)
class HistoryObservation:
    preflight: HistoryPreflight
    reused: bool = False


class VerifiedHistoryReuse:
    """Single bounded cache entry, owned by a trusted runtime, not request input.

    Every reuse needs a fresh authenticated version read. On miss, S1
    verification runs and the version is read again to detect observed changes.
    Unavailable versioning disables reuse but does not block ordinary full
    verification. A changed version during a full read prevents reuse and
    downgrades a positive finding. Actual blocker records are never cached as
    clean or discarded due to an unstable version. No provider can consume
    the result as authorization; ordinary gates must be refreshed separately.
    """
    def __init__(self, *, authority_id: str, central_revision: str,
                 probe: Callable[[RecoveryRequest], HistoryVersion], reader: TrustedReader,
                 verify_scope: TrustedVerifier, verify_coverage: TrustedVerifier):
        if not isinstance(authority_id, str) or not authority_id.strip() or not isinstance(central_revision, str) or not re.fullmatch(r"[0-9a-f]{40}", central_revision):
            raise ValueError("trusted authority and exact pin required")
        self._authority = authority_id
        self._revision = central_revision
        self._probe = probe
        self._reader = reader
        self._scope = verify_scope
        self._coverage = verify_coverage
        self._entry: tuple[HistoryVersion, HistoryPreflight] | None = None
        self._lock = RLock()

    def _version(self, request: RecoveryRequest) -> HistoryVersion | None:
        try:
            v = self._probe(request)
            if not isinstance(v, HistoryVersion) or v.request != request or v.authority_id != self._authority or v.central_revision != self._revision:
                return None
            return v
        except Exception:
            return None

    def observe(self, request: RecoveryRequest) -> HistoryObservation:
        if not isinstance(request, RecoveryRequest):
            raise TypeError("typed request required")
        with self._lock:
            before = self._version(request)
            if before is not None and self._entry is not None and self._entry[0] == before:
                return HistoryObservation(self._entry[1], reused=True)
            self._entry = None
            captured: list[HistoryEvidence] = []

            def read(req: RecoveryRequest) -> HistoryEvidence:
                value = self._reader(req)
                captured.append(value)
                return value

            result = observe_history(request, reader=read, verify_scope=self._scope,
                                     verify_coverage=self._coverage)
            if result.recovery.status is not RecoveryStatus.HISTORY_VERIFIED:
                return HistoryObservation(result)
            # No trusted version at start: ordinary full verification only.
            if before is None:
                return HistoryObservation(result)
            after = self._version(request)
            if after != before or len(captured) != 1 or evidence_digest(captured[0]) != before.digest:
                return HistoryObservation(HistoryPreflight(request, RecoveryResult(
                    RecoveryStatus.HISTORY_INCOMPLETE, result.recovery.work_id,
                    result.recovery.historical_work_ids,
                    reason="authoritative evidence version changed or digest mismatch")))
            self._entry = (before, result)
            return HistoryObservation(result)
