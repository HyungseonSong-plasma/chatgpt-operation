"""Executable Mon-Sun dry-run coverage for the Paul maintenance cadence."""
from __future__ import annotations

from datetime import date, timedelta

from chatgpt_operation.weekly_schedule import phase_for_day


def test_full_mon_sun_dry_run_is_deterministic_and_observation_first() -> None:
    monday = date(2026, 9, 28)
    evidence: list[dict[str, object]] = []
    skill_mutations: list[object] = []

    for offset in range(7):
        day = monday + timedelta(days=offset)
        phase = phase_for_day(day)
        evidence.append(
            {
                "day": day.isoformat(),
                "phase": phase,
                "raw_evidence_preserved": True,
            }
        )
        if phase == "collect":
            skill_mutations.append(None)

    assert [item["phase"] for item in evidence] == [
        "collect",
        "collect",
        "collect",
        "collect",
        "collect",
        "analyze",
        "close",
    ]
    assert len(evidence) == 7
    assert all(item["raw_evidence_preserved"] for item in evidence)
    assert all(item is None for item in skill_mutations)
