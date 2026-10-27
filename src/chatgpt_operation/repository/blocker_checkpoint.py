"""Independently sourced checkpoint for detecting loss/rewrite of journal tail.

An event hash-chain cannot detect truncation of its most recent valid entries.
The expected tip must come from a separately governed, trusted anchor that
the Issue-comment writer cannot silently rewrite. This code validates proof,
it does not provision an immutable provider or permission.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from .blocker_journal import JournalError, JournalSnapshot, ZERO


@dataclass(frozen=True)
class JournalCheckpoint:
    sequence: int
    tip: str
    anchor_ref: str

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 1:
            raise ValueError("anchor must attest at least one durable event")
        if (not isinstance(self.tip, str)
                or not re.fullmatch(r"[0-9a-f]{64}", self.tip)
                or self.tip == ZERO):
            raise ValueError("anchor tip must be a nonzero SHA-256 digest")
        if not isinstance(self.anchor_ref, str) or not self.anchor_ref.strip():
            raise ValueError("independent anchor source reference required")


def require_checkpoint(snapshot: JournalSnapshot, checkpoint: JournalCheckpoint) -> None:
    """Block use of missing, truncated, rewritten or not-yet-anchored journals.

    A correct checkpoint does not prove independence of its source. The
    trusted deployment must fetch it from a distinct authority/storage
    boundary, not a sibling Issue comment or self-reported ActionPlan.
    """
    if not isinstance(snapshot, JournalSnapshot):
        raise JournalError("verified journal snapshot required")
    if not isinstance(checkpoint, JournalCheckpoint):
        raise JournalError("trusted independent checkpoint required")
    if len(snapshot.events) != checkpoint.sequence or snapshot.tip != checkpoint.tip:
        raise JournalError("journal does not match independently anchored tip")
