"""Attest Gemini review receipt to a prepared GitHub-sourced request.

The receipt is evidence of a bounded *model response*, never a PR approval.
External model text remains untrusted even after binding.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from .gemini_review_adapter import ReviewError, canonical_bytes, validate_packet


def bind_review_receipt(prepared: object, result: object) -> dict:
    if not isinstance(prepared, dict) or prepared.get("status") != "VERIFIED_REVIEW_REQUEST":
        raise ReviewError("unverified Gemini request receipt")
    packet = validate_packet(prepared.get("packet"))
    if prepared.get("request_sha256") != hashlib.sha256(canonical_bytes(packet)).hexdigest():
        raise ReviewError("request receipt digest mismatch")
    if not isinstance(result, dict) or result.get("status") not in {"UNKNOWN", "REVIEW_RETURNED"}:
        raise ReviewError("missing or invalid Gemini execution result")
    outcome = result["status"]
    if outcome == "REVIEW_RETURNED":
        for key, expected in (
            ("request_sha256", prepared["request_sha256"]),
            ("repository", packet["repository"]),
            ("base_sha", packet["base_sha"]),
            ("head_sha", packet["head_sha"]),
            ("diff_sha256", packet["diff_sha256"]),
        ):
            if result.get(key) != expected:
                raise ReviewError("stale or forged Gemini response identity")
        if (result.get("provider") != "gemini"
                or result.get("mutation_authorized") is not False
                or result.get("merge_authorized") is not False
                or result.get("semantic_acceptance") != "REVIEW_REQUIRED"):
            raise ReviewError("Gemini response claims unauthorized authority")
        review = result.get("verdict")
        if not isinstance(review, dict) or review.get("verdict") not in {
            "PASS", "REQUEST_CHANGES", "UNKNOWN",
        }:
            raise ReviewError("unrecognized Gemini review verdict")
        verdict = review["verdict"]
    else:
        if result.get("merge_authorized") is not False or result.get("mutation_authorized") is not False:
            raise ReviewError("unknown result must deny mutation authority")
        verdict = "UNKNOWN"
        code = result.get("failure_code")
        if code is not None and (
            not isinstance(code, str) or
            re.fullmatch(
                r"(?:API_HTTP_[1-5][0-9]{2}|API_KEY_MISSING|API_TRANSPORT_ERROR|"
                r"CANDIDATES_INVALID|GENERATION_INCOMPLETE|MODEL_CONTENT_INVALID|"
                r"MODEL_JSON_INVALID|REVIEW_SCHEMA_INVALID|INPUT_OR_REVIEW_INVALID|"
                r"REQUEST_INVALID|UNKNOWN_FAILURE)",
                code,
            ) is None
        ):
            raise ReviewError("invalid sanitized provider failure code")
    return {
        "schema_version": 1,
        "status": "REVIEW_RECEIPT_BOUND" if outcome == "REVIEW_RETURNED" else "UNKNOWN",
        "review_verdict": verdict,
        "human_adjudication": "REQUIRED",
        "repository": packet["repository"],
        "source_pr_number": prepared["source_pr_number"],
        "base_sha": packet["base_sha"],
        "head_sha": packet["head_sha"],
        "diff_sha256": packet["diff_sha256"],
        "request_sha256": prepared["request_sha256"],
        "issue_number": prepared["issue_number"],
        "model_result": result if outcome == "REVIEW_RETURNED" else {
            "status": "UNKNOWN", "failure": result.get("failure"),
            **({"failure_code": result["failure_code"]}
               if "failure_code" in result else {}),
        },
        "merge_authorized": False,
        "mutation_authorized": False,
        "semantic_acceptance": "REVIEW_REQUIRED",
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Bind Gemini result to trusted review request")
    p.add_argument("--request", required=True)
    p.add_argument("--result", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args(argv)
    try:
        prepared = json.loads(Path(args.request).read_text(encoding="utf-8"))
        observed = json.loads(Path(args.result).read_text(encoding="utf-8"))
        receipt = bind_review_receipt(prepared, observed)
    except (ReviewError, OSError, UnicodeError, ValueError, TypeError) as exc:
        print("SAMUEL_GEMINI_RECEIPT=UNKNOWN (" + type(exc).__name__ + ")", file=sys.stderr)
        return 2
    Path(args.output).write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
    print("SAMUEL_GEMINI_RECEIPT=" + receipt["status"])
    return 0 if receipt["status"] == "REVIEW_RECEIPT_BOUND" else 2


if __name__ == "__main__":
    raise SystemExit(main())
