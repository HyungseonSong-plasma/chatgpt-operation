"""Host/scheduler boundary for Samuel.

A ChatGPT-hosted or other external scheduler is a wake-up trigger, not the
Samuel controller. It may dispatch only the canonical bootstrap workflow.
All work selection and repository mutation authority live behind that workflow.
"""
from __future__ import annotations

CANONICAL_BOOTSTRAP_WORKFLOW = "samuel-bootstrap.yml"
CANONICAL_BOOTSTRAP_REF = "main"


class HostBoundaryError(RuntimeError):
    pass


def validate_host_operation(*, operation: str, workflow: str | None = None, ref: str | None = None) -> None:
    if operation != "dispatch_workflow":
        raise HostBoundaryError("external scheduler may only dispatch the canonical Samuel bootstrap")
    if workflow != CANONICAL_BOOTSTRAP_WORKFLOW or ref != CANONICAL_BOOTSTRAP_REF:
        raise HostBoundaryError("external scheduler dispatch target is not the canonical Samuel bootstrap")


def scheduled_controller_contract() -> dict[str, object]:
    return {
        "role": "bootstrap_trigger_only",
        "operation": "dispatch_workflow",
        "workflow": CANONICAL_BOOTSTRAP_WORKFLOW,
        "ref": CANONICAL_BOOTSTRAP_REF,
        "forbidden": [
            "select_work",
            "repository_write",
            "merge_pr",
            "comment_issue",
            "close_issue",
            "direct_native_execution",
        ],
    }
