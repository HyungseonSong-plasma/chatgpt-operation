"""Deterministic Saturday analysis over a pinned raw-evidence snapshot."""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping


def analyze_snapshot(observations: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Return a stable, JSON-serializable summary without mutating evidence."""
    normalized = [dict(item) for item in observations]
    normalized.sort(
        key=lambda item: (
            str(item.get("occurred_at", "")),
            str(item.get("identity", "")),
        )
    )

    by_consumer = Counter(str(item.get("consumer", "UNKNOWN")) for item in normalized)
    by_category = Counter(
        str(item.get("failure_category", "UNKNOWN")) for item in normalized
    )
    signatures = Counter(
        str(item["failure_signature"])
        for item in normalized
        if item.get("failure_signature") is not None
    )

    return {
        "observation_count": len(normalized),
        "consumer_counts": dict(sorted(by_consumer.items())),
        "failure_category_counts": dict(sorted(by_category.items())),
        "repeated_failure_signatures": dict(
            sorted((signature, count) for signature, count in signatures.items() if count > 1)
        ),
        "observation_identities": [
            str(item.get("identity", "")) for item in normalized
        ],
    }
