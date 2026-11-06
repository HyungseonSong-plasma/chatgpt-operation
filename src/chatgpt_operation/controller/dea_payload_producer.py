"""Local DEA v2 payload creator for a future approved Actions producer job.

Consumes existing JSON observations/metrics/summary and writes a
deterministic, signable evidence package. Does not sign, upload, dispatch,
run candidate code, or assert that the inputs are truthful.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from chatgpt_operation.controller.dea_attested_payload import (
    PayloadContractError, build_payload,
)

_MAX_JSON = 5_000_000


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for k, v in pairs:
        if k in obj:
            raise PayloadContractError("duplicate producer input JSON keys")
        obj[k] = v
    return obj


def _nonfinite(x: str) -> None:
    raise PayloadContractError("nonfinite producer input number")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size > _MAX_JSON:
        raise PayloadContractError("producer input missing or too large")
    try:
        obj = json.loads(path.read_text(encoding="utf-8"),
                         object_pairs_hook=_no_duplicates,
                         parse_constant=_nonfinite)
    except (ValueError, UnicodeError, OSError) as exc:
        raise PayloadContractError("producer input JSON invalid") from exc
    if not isinstance(obj, dict):
        raise PayloadContractError("producer input is not an object")
    return obj


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repository", required=True)
    p.add_argument("--run-id", type=int, required=True)
    p.add_argument("--candidate-head", required=True)
    p.add_argument("--analyzed-source-sha", required=True)
    p.add_argument("--oracle-revision-sha", required=True)
    p.add_argument("--measurement-set-sha", required=True)
    p.add_argument("--observations-json", type=Path, required=True)
    p.add_argument("--metrics-json", type=Path, required=True)
    p.add_argument("--summary-json", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args(argv)
    try:
        if a.output.name != "dea-evidence.zip" or not a.output.parent.is_dir():
            raise PayloadContractError("signable output must be dea-evidence.zip")
        evidence = build_payload(
            repository=a.repository, run_id=a.run_id,
            candidate_head_sha=a.candidate_head,
            analyzed_source_sha=a.analyzed_source_sha,
            oracle_revision_sha=a.oracle_revision_sha,
            measurement_set_sha=a.measurement_set_sha,
            observations=_read_json(a.observations_json),
            metrics=_read_json(a.metrics_json),
            summary=_read_json(a.summary_json),
        )
        # Never overwrite a previous signed subject. A new attempt gets a
        # new output directory and must be tied to a distinct Actions run.
        with a.output.open("xb") as stream:
            stream.write(evidence)
    except (PayloadContractError, OSError):
        print(json.dumps({
            "status": "HUMAN_REVIEW_REQUIRED",
            "phase": "PRODUCER_PACKAGE",
            "automatic_fitness_pass": False,
            "review_delivery": "NOT_CONFIGURED",
        }, sort_keys=True))
        return 2
    from hashlib import sha256
    print(json.dumps({
        "status": "UNATTESTED_SUBJECT_READY",
        "subject_sha256": sha256(evidence).hexdigest(),
        "output_file": a.output.name,
        "run_id": a.run_id,
        "artifact_id": None,
        "automatic_fitness_pass": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
