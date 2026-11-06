"""Trusted-host composition for the DEA #254 protected Workflow Draft PR broker.

THIS MODULE IS NOT THE CHATGPT-HOSTED GITHUB CONNECTOR. It exposes a
narrow application entrypoint for a separately deployed, privileged host
whose GitHub App credential, independent journal checkpoint, and authority
verification callbacks are provisioned outside model-supplied arguments.

The host must NOT expose arbitrary GitHubTransport methods to the model.
The module does not register a plugin, reconfigure a ChatGPT connector,
change existing GitHub App scopes, or grant any write permission.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from chatgpt_operation.controller.dea_trusted_workflow_authoring_adapter import (
    REPO, GitHubBoundTransport, TrustedWorkflowDraftAdapter, WorkflowDraftReceipt,
    WorkflowAuthoringError,
)
from chatgpt_operation.repository.blocker_checkpoint import JournalCheckpoint
from chatgpt_operation.repository.blocker_gate import CommonPreWriteGate
from chatgpt_operation.repository.blocker_journal import GitHubIssueBlockerJournal
from chatgpt_operation.repository.blocker_resolution import ClearanceEvidence
from chatgpt_operation.repository.blocker_verifiers import TrustedGitHubReadbacks


@dataclass(frozen=True)
class HostOwnedTrustConfig:
    """Injected from trusted service deployment, NEVER from an ActionPlan.

    Security-critical callbacks must be backed by independent managed
    infrastructure. A user-supplied function that simply returns an
    affirmative response is not proof of policy authority or journal
    integrity. The host must reject misconfigured integrations.
    """

    journal_issue_number: int
    trusted_journal_actor: str
    independent_checkpoint_reader: Callable[[], JournalCheckpoint]
    policy_authority_verifier: Callable[[ClearanceEvidence], bool]


class HostedDeaDraftService:
    """Public service API is solely a Draft PR creation intent.

    No service-level method to merge, dispatch a protected Workflow,
    update policy, change permissions or invoke arbitrary GitHub paths.
    """

    def __init__(
        self,
        *,
        github_transport: GitHubBoundTransport,
        host_config: HostOwnedTrustConfig,
    ) -> None:
        if getattr(github_transport, "repository", None) != REPO:
            raise WorkflowAuthoringError("HOST_GITHUB_REPOSITORY_MISMATCH")
        if not isinstance(host_config, HostOwnedTrustConfig):
            raise WorkflowAuthoringError("HOST_TRUST_CONFIG_REQUIRED")
        if (type(host_config.journal_issue_number) is not int
                or host_config.journal_issue_number <= 0
                or not isinstance(host_config.trusted_journal_actor, str)
                or not host_config.trusted_journal_actor.strip()
                or not callable(host_config.independent_checkpoint_reader)
                or not callable(host_config.policy_authority_verifier)):
            raise WorkflowAuthoringError("HOST_TRUST_CONFIG_INVALID")
        self._readbacks = TrustedGitHubReadbacks(
            github_transport, repository=REPO, branch="main",
        )
        self._journal = GitHubIssueBlockerJournal(
            github_transport,
            issue_number=host_config.journal_issue_number,
            trusted_actor=host_config.trusted_journal_actor,
        )
        self._gate = CommonPreWriteGate(
            journal=self._journal,
            trusted_head_reader=self._readbacks.read_head,
            technical_verifier=self._readbacks.verify_technical,
            authority_verifier=host_config.policy_authority_verifier,
            trusted_checkpoint_reader=host_config.independent_checkpoint_reader,
        )
        self._adapter = TrustedWorkflowDraftAdapter(
            transport=github_transport, blocker_gate=self._gate,
        )

    def create_review_only_draft(
        self, *, expected_main_sha: str,
    ) -> WorkflowDraftReceipt:
        """Perform the one eligible scoped write sequence, if independently authorized.

        A trusted service must authenticate the caller and prove real
        adoption authority BEFORE invoking this method. This method does
        not treat conversational approval or static CI as a clearance.
        """
        return self._adapter.prepare_and_create_draft(
            expected_main_sha=expected_main_sha,
        )


def connect_hosted_dea_workflow_authoring(
    *,
    github_transport: GitHubBoundTransport,
    host_config: HostOwnedTrustConfig,
) -> HostedDeaDraftService:
    """Compose authenticated GitHub readbacks + journal + gate + write adapter.

    Do not call from the existing unguarded GitHub connector. A new
    externally deployed trusted integration must route requests here.
    """
    return HostedDeaDraftService(
        github_transport=github_transport,
        host_config=host_config,
    )
