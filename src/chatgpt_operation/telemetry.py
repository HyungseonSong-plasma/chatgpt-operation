"""Non-authoritative skill activation telemetry primitives."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone

REQUIRED = ("event", "skill", "skill_path", "consumer", "central_revision", "trigger", "observed_at")

class TelemetryError(ValueError):
    pass

def _utc_day(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TelemetryError("observed_at must be ISO-8601") from exc
    if dt.tzinfo is None:
        raise TelemetryError("observed_at must include timezone")
    return dt.astimezone(timezone.utc).date().isoformat()

def validate(event: dict) -> dict:
    if not isinstance(event, dict):
        raise TelemetryError("event must be an object")
    missing = [key for key in REQUIRED if not event.get(key)]
    if missing:
        raise TelemetryError("missing fields: " + ", ".join(missing))
    if event["event"] != "skill_activation":
        raise TelemetryError("unsupported event")
    revision = event["central_revision"]
    if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision.lower()):
        raise TelemetryError("central_revision must be a 40-hex commit")
    _utc_day(event["observed_at"])
    return dict(event)

def identity(event: dict) -> str:
    """Stable retry identity. Producers should provide activation_id when available."""
    event = validate(event)
    if event.get("activation_id"):
        basis = [event["consumer"], event["central_revision"], event["skill_path"], str(event["activation_id"])]
    else:
        basis = [event[key] for key in ("consumer", "central_revision", "skill_path", "trigger", "observed_at")]
    return hashlib.sha256("\0".join(basis).encode()).hexdigest()

def aggregate(events: list[dict], known_skills: list[str] | None = None) -> dict:
    """Deterministically aggregate unique activation events."""
    unique = {}
    for raw in events:
        event = validate(raw)
        unique.setdefault(identity(event), event)
    ordered = [unique[key] for key in sorted(unique)]
    by_skill_day = Counter((e["skill"], _utc_day(e["observed_at"])) for e in ordered)
    by_skill_consumer = Counter((e["skill"], e["consumer"]) for e in ordered)
    by_trigger = Counter(e["trigger"] for e in ordered)
    weeks = Counter()
    for e in ordered:
        dt = datetime.fromisoformat(e["observed_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
        year, week, _ = dt.isocalendar()
        weeks[f"{year}-W{week:02d}"] += 1
    observed = {e["skill"] for e in ordered}
    return {
        "event_count": len(ordered),
        "duplicate_count": len(events) - len(ordered),
        "activations_by_skill_day": {f"{s}|{d}": n for (s,d),n in sorted(by_skill_day.items())},
        "activations_by_skill_consumer": {f"{s}|{c}": n for (s,c),n in sorted(by_skill_consumer.items())},
        "activations_by_trigger": dict(sorted(by_trigger.items())),
        "total_activations_by_week": dict(sorted(weeks.items())),
        "skills_with_zero_observed_activation": sorted(set(known_skills or []) - observed),
    }

def parse_jsonl(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]
