"""Provider qualification and non-executing shadow evaluation."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .issue_reasoning import IssueReasoningProposal
from .reasoning_provider import ProviderRequestFailure


class QualificationFailure(str, Enum):
    SCHEMA_INVALID = "schema_invalid"
    DECISION_DRIFT = "decision_drift"
    EVIDENCE_UNGROUNDED = "evidence_ungrounded"
    FALSE_BLOCKED = "false_blocked"


@dataclass(frozen=True)
class QualificationCase:
    case_id: str
    context: dict[str, Any]
    allowed_decision_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ShadowResult:
    case_id: str
    provider: str
    passed: bool
    failures: tuple[QualificationFailure, ...]
    proposal: IssueReasoningProposal | None
    executed: bool = False
    provider_failure: dict[str, Any] | None = None
    schema_error: str | None = None
    raw_proposal: dict[str, Any] | None = None


def evaluate_shadow(
    *,
    provider: Any,
    case: QualificationCase,
) -> ShadowResult:
    """Run semantic reasoning without ever producing an executable dispatch."""
    failures: list[QualificationFailure] = []
    proposal: IssueReasoningProposal | None = None
    try:
        raw = provider.reason(
            task="Produce one typed Samuel Issue reasoning proposal.",
            context=case.context,
            attempt=1,
            validation_error=None,
        )
        proposal = IssueReasoningProposal.from_dict(raw)
    except ProviderRequestFailure as exc:
        return ShadowResult(
            case.case_id, provider.name, False, tuple(failures), None, False,
            {
                "kind": exc.kind,
                "status": exc.status,
                "provider_code": exc.provider_code,
                "retryable": exc.retryable,
            },
        )
    except (TypeError, ValueError) as exc:
        failures.append(QualificationFailure.SCHEMA_INVALID)
        safe_raw = raw if isinstance(locals().get("raw"), dict) else None
        return ShadowResult(
            case.case_id, provider.name, False, tuple(failures), None, False,
            None, str(exc), safe_raw,
        )

    if proposal.decision_id is not None and proposal.decision_id not in case.allowed_decision_ids:
        failures.append(QualificationFailure.DECISION_DRIFT)

    # Evidence references are optional in the current proposal schema. If a provider
    # supplies them inside an ActionPlan, every reference must be present in the
    # bounded qualification envelope.
    plan = proposal.action_plan or {}
    refs = plan.get("evidence_ids", [])
    if refs and (
        not isinstance(refs, list)
        or any(not isinstance(x, str) or x not in case.evidence_ids for x in refs)
    ):
        failures.append(QualificationFailure.EVIDENCE_UNGROUNDED)

    return ShadowResult(
        case.case_id, provider.name, not failures, tuple(failures), proposal, False
    )


def qualify(provider: Any, cases: list[QualificationCase]) -> list[ShadowResult]:
    if not cases:
        raise ValueError("qualification requires at least one case")
    return [evaluate_shadow(provider=provider, case=case) for case in cases]
