"""Non-authoritative per-run Skill governance telemetry for Samuel."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any

MARKER = "<!-- samuel-skill-utilization-telemetry -->"
SCHEMA_VERSION = 1


class SkillTelemetryError(ValueError):
    pass


def _ratio(n: int, d: int) -> float | None:
    return None if d == 0 else n / d


def _fmt(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.3f}"


def _catalog(path: str | Path) -> dict[str, Any]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1 or not isinstance(raw.get("skills"), list):
        raise SkillTelemetryError("invalid skill catalog")
    return raw


def build_run_record(
    cycle: dict[str, Any],
    *,
    event_name: str,
    run_id: int,
    head_sha: str,
    repository: str,
    catalog_path: str | Path = "skills/catalog.json",
    repository_root: str | Path = ".",
) -> dict[str, Any]:
    """Measure only mechanically observed resolution/consultation/application."""
    if cycle.get("schema_version") != 4:
        raise SkillTelemetryError("unsupported controller cycle schema")
    if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id < 1:
        raise SkillTelemetryError("run_id must be positive")
    if not isinstance(head_sha, str) or len(head_sha) != 40:
        raise SkillTelemetryError("head_sha must be a 40-character identity")
    triggers = {"RESEARCH_CONTROLLER"}
    if event_name == "schedule":
        triggers.add("SCHEDULED_CONTROLLER")

    resolved_entries = sorted(
        (
            item
            for item in _catalog(catalog_path)["skills"]
            if triggers.intersection(str(x) for x in item.get("load_on", []))
        ),
        key=lambda item: str(item["name"]),
    )
    resolved = [str(item["name"]) for item in resolved_entries]

    # A Skill counts as consulted only when its README is actually read here.
    consulted_entries = [
        item for item in resolved_entries if item["name"] == "research-controller"
    ]
    root = Path(repository_root)
    for item in consulted_entries:
        text = (root / str(item["path"])).read_text(encoding="utf-8")
        if not text.strip():
            raise SkillTelemetryError("consulted Skill README is empty")
    consulted = [str(item["name"]) for item in consulted_entries]

    selected = cycle.get("selected_work")
    if not isinstance(selected, dict):
        raise SkillTelemetryError("selected_work is missing")
    material = sum(
        cycle.get(key) is not None
        for key in ("admission_write", "state_write", "execution_command")
    )
    if selected.get("kind") not in {None, "idle"}:
        material += 1

    applied_entries = consulted_entries if material else []
    applied = [str(item["name"]) for item in applied_entries]
    governed = material if applied else 0
    evidence = [
        {
            "skill": str(item["name"]),
            "path": str(item["path"]),
            "governed": (
                "SamuelController composition-root contracts governed work "
                "selection and typed state/action output."
            ),
        }
        for item in applied_entries
    ]
    return {
        "schema_version": 1,
        "run_id": run_id,
        "repository": repository,
        "head_sha": head_sha,
        "event_name": event_name,
        "selected_kind": str(selected.get("kind") or ""),
        "resolved_skills": resolved,
        "consulted_skills": consulted,
        "applied_skills": applied,
        "applied_skill_evidence": evidence,
        "governed_actions": governed,
        "total_material_actions": material,
        "unused_resolved_skills": sorted(set(resolved) - set(consulted)),
        "metrics": {
            "resolution_coverage": _ratio(len(consulted), len(resolved)),
            "application_rate": _ratio(len(applied), len(consulted)),
            "action_governance_rate": _ratio(governed, material),
        },
    }


def _history(body: str | None) -> dict[str, Any]:
    if not body or MARKER not in body:
        return {"schema_version": SCHEMA_VERSION, "runs": []}
    start = body.find("~~~json")
    end = body.rfind("~~~")
    if start < 0 or end <= start + 7:
        raise SkillTelemetryError("telemetry JSON fence missing")
    raw = json.loads(body[start + 7:end].strip())
    if raw.get("schema_version") != SCHEMA_VERSION or not isinstance(raw.get("runs"), list):
        raise SkillTelemetryError("invalid telemetry history")
    return raw


def summarize(history: dict[str, Any]) -> dict[str, Any]:
    runs = history["runs"]
    totals = {
        "resolved": sum(len(x["resolved_skills"]) for x in runs),
        "consulted": sum(len(x["consulted_skills"]) for x in runs),
        "applied": sum(len(x["applied_skills"]) for x in runs),
        "governed_actions": sum(int(x["governed_actions"]) for x in runs),
        "total_material_actions": sum(int(x["total_material_actions"]) for x in runs),
    }
    unused = Counter(
        skill for run in runs for skill in run.get("unused_resolved_skills", [])
    )
    trailing = None
    if len(runs) >= 5:
        trailing = {}
        for key in ("resolution_coverage", "application_rate", "action_governance_rate"):
            values = [x["metrics"][key] for x in runs[-5:] if x["metrics"][key] is not None]
            trailing[key] = None if not values else sum(values) / len(values)
    return {
        "run_count": len(runs),
        "cumulative": {
            **totals,
            "resolution_coverage": _ratio(totals["consulted"], totals["resolved"]),
            "application_rate": _ratio(totals["applied"], totals["consulted"]),
            "action_governance_rate": _ratio(
                totals["governed_actions"], totals["total_material_actions"]
            ),
            "ungoverned_material_actions": (
                totals["total_material_actions"] - totals["governed_actions"]
            ),
        },
        "trailing_5_run_averages": trailing,
        "recurring_unused_skills": [
            {"skill": name, "runs": count}
            for name, count in sorted(unused.items())
            if count >= 2
        ],
    }


def merge_run(
    existing_body: str | None,
    record: dict[str, Any],
    *,
    max_runs: int = 50,
) -> tuple[str, dict[str, Any]]:
    """Deduplicate retries by GitHub run id and render one rolling Issue #43 comment."""
    history = _history(existing_body)
    by_id = {int(item["run_id"]): item for item in history["runs"]}
    by_id[int(record["run_id"])] = record
    runs = [by_id[key] for key in sorted(by_id)][-max_runs:]
    history = {"schema_version": SCHEMA_VERSION, "runs": runs}
    summary = summarize(history)
    current = runs[-1]
    cumulative = summary["cumulative"]
    trailing = summary["trailing_5_run_averages"]
    trailing_text = (
        "N/A (<5 runs)"
        if trailing is None
        else ", ".join(f"{k}={_fmt(v)}" for k, v in trailing.items())
    )
    recurring = summary["recurring_unused_skills"]
    recurring_text = (
        "none"
        if not recurring
        else ", ".join(f"{x['skill']} ({x['runs']} runs)" for x in recurring)
    )
    current_ungoverned = (
        int(current["total_material_actions"]) - int(current["governed_actions"])
    )
    body = "\n".join(
        [
            MARKER,
            "## Samuel Skill utilization telemetry",
            "",
            f"Current run: `{current['run_id']}` / `{current['selected_kind']}`",
            (
                "Current metrics: "
                f"resolution_coverage={_fmt(current['metrics']['resolution_coverage'])}, "
                f"application_rate={_fmt(current['metrics']['application_rate'])}, "
                f"action_governance_rate={_fmt(current['metrics']['action_governance_rate'])}"
            ),
            (
                "Current counts: "
                f"resolved={len(current['resolved_skills'])}, "
                f"consulted={len(current['consulted_skills'])}, "
                f"applied={len(current['applied_skills'])}, "
                f"governed_actions={current['governed_actions']}, "
                f"total_material_actions={current['total_material_actions']}, "
                f"ungoverned={current_ungoverned}"
            ),
            (
                "Cumulative: "
                f"runs={summary['run_count']}, "
                f"resolution_coverage={_fmt(cumulative['resolution_coverage'])}, "
                f"application_rate={_fmt(cumulative['application_rate'])}, "
                f"action_governance_rate={_fmt(cumulative['action_governance_rate'])}, "
                f"ungoverned_material_actions={cumulative['ungoverned_material_actions']}"
            ),
            f"Trailing 5-run averages: {trailing_text}",
            f"Recurring unused resolved Skills: {recurring_text}",
            "",
            "Applied Skill evidence:",
            *(
                [
                    f"- `{x['skill']}` — `{x['path']}` — {x['governed']}"
                    for x in current["applied_skill_evidence"]
                ]
                or ["- none"]
            ),
            "",
            "~~~json",
            json.dumps(history, sort_keys=True, separators=(",", ":")),
            "~~~",
        ]
    )
    return body, summary


def find_comment(comments: list[dict[str, Any]]) -> dict[str, Any] | None:
    matches = [x for x in comments if MARKER in str(x.get("body", ""))]
    if len(matches) > 1:
        raise SkillTelemetryError("multiple Skill telemetry comments")
    return matches[0] if matches else None
