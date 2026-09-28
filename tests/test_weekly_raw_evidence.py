from __future__ import annotations

import json

from chatgpt_operation.weekly_raw_evidence import RawEvidenceStore


def test_weekday_raw_evidence_is_durable_and_duplicate_safe(tmp_path) -> None:
    path = tmp_path / "weekly-evidence.jsonl"
    store = RawEvidenceStore(path)
    observation = {
        "consumer": "simulation-ontology",
        "occurred_at": "2026-09-28T17:00:00Z",
        "phase": "collect",
        "skill_mutated": False,
        "workflow_failure": "UNKNOWN",
    }

    first = store.append(observation)
    duplicate = store.append(dict(observation))

    assert duplicate == first
    assert store.read() == (first,)
    assert path.read_text(encoding="utf-8").count("\n") == 1
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["payload"] == observation
    assert observation["skill_mutated"] is False
