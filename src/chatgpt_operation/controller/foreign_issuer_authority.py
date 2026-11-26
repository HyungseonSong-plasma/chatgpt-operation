"""GitHub-native owner approval and independent completed issuer-run evidence.

This is the concrete read side of the protected issuer workflow contract.
The trusted composition root supplies an authenticated GET/artifact transport
and independently adopted immutable workflow/owner/environment configuration.
No token acquisition, writes, inferred history, lease, revocation or clearance.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from io import BytesIO
import json
import re
from zipfile import ZipFile

from .foreign_issuance import require
from .foreign_work_issuer import FirstIssuance, canonical, valid_sha

WORKFLOW = '.github/workflows/samuel-foreign-issuer.yml'
ARTIFACT_FILE = 'issuance-receipt.json'
JOB = 'publish'
STEP = 'Publish exact protected issuance'


def request_digest(record, paths):
    # Exclude server-assigned run and review references from the dispatch input.
    require(isinstance(record, FirstIssuance) and isinstance(paths, tuple)
            and bool(paths) and all(isinstance(p, str) and bool(p) for p in paths),
            'INVALID_ISSUER_REQUEST')
    return sha256(canonical({'binding': asdict(record.binding),
                             'target_head': record.target_head,
                             'history_digest': record.history_digest,
                             'paths': list(paths)})).hexdigest()


def publication_receipt(record, commit, raw, paths):
    require(valid_sha(commit) and isinstance(raw, bytes)
            and raw == canonical(record.payload(paths)), 'PUBLICATION_PAYLOAD_MISMATCH')
    return {'schema': 'samuel.foreign-issuance-receipt.v1',
            'request_sha256': request_digest(record, paths), 'ref': record.ref,
            'commit': commit, 'payload_sha256': sha256(raw).hexdigest(),
            'publisher_ref': record.publisher_ref, 'approval_ref': record.approval_ref,
            'work_enrolled': False, 'controller_execution_approved': False}


@dataclass(frozen=True)
class IssuerAuthorityConfig:
    repository: str
    repository_id: int
    owner_id: int
    environment_id: int
    environment: str
    workflow_blob: str

    def __post_init__(self):
        require(isinstance(self.repository, str) and bool(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', self.repository))
                and all(type(x) is int and x > 0 for x in
                        (self.repository_id, self.owner_id, self.environment_id))
                and isinstance(self.environment, str) and bool(re.fullmatch(r'[A-Za-z0-9_.-]+', self.environment))
                and valid_sha(self.workflow_blob), 'TRUSTED_ISSUER_CONFIGURATION_REQUIRED')


class GitHubIssuerAuthority:
    """Verify exact GitHub owner approval and completed publication evidence.

    A completed run with a matching artifact is required for independent
    readback. In-progress publication cannot be promoted to a verified receipt.
    Live approval is deliberately not a lease or proof of historical coverage.
    A separate current-authority/revocation verifier remains mandatory when
    composing ForeignEnrollmentAuthority.
    """
    def __init__(self, *, config, transport, paths):
        require(isinstance(config, IssuerAuthorityConfig)
                and callable(getattr(transport, 'get', None))
                and callable(getattr(transport, 'artifact_zip', None))
                and isinstance(paths, tuple) and bool(paths), 'TRUSTED_ISSUER_TRANSPORT_REQUIRED')
        self.config, self.transport, self.paths = config, transport, paths
        self.root = '/repos/' + config.repository

    def _run_id(self, record):
        require(isinstance(record, FirstIssuance), 'TYPED_ISSUANCE_REQUIRED')
        match = re.fullmatch(r'github-actions-run:([1-9][0-9]*):1', record.publisher_ref)
        require(match is not None, 'PUBLISHER_REF_INVALID')
        run_id = int(match.group(1))
        require(record.approval_ref == f'github-environment:{self.config.environment_id}:run:{run_id}:1',
                'APPROVAL_REF_MISMATCH')
        return run_id

    def _approval_comment(self, record):
        return ('APPROVE FOREIGN ISSUANCE ' + request_digest(record, self.paths)
                + ' payload:' + sha256(canonical(record.payload(self.paths))).hexdigest()
                + ' run:' + str(self._run_id(record)) + ' attempt:1')

    def _observe(self, record, *, status):
        cfg = self.config
        run_id = self._run_id(record)
        repo = self.transport.get(self.root)
        require(type(repo.get('id')) is int and repo['id'] == cfg.repository_id
                and repo.get('full_name') == cfg.repository, 'AUTHORITY_REPOSITORY_MISMATCH')
        path = self.root + '/actions/runs/' + str(run_id)
        run = self.transport.get(path)
        require(type(run.get('id')) is int and run['id'] == run_id
                and type(run.get('run_attempt')) is int and run['run_attempt'] == 1
                and run.get('event') == 'workflow_dispatch'
                and run.get('path') in (WORKFLOW, WORKFLOW + '@refs/heads/main')
                and run.get('head_branch') == 'main'
                and run.get('head_sha') == record.binding.central_revision
                and run.get('repository', {}).get('id') == cfg.repository_id
                and run.get('head_repository', {}).get('id') == cfg.repository_id
                and run.get('actor', {}).get('id') == cfg.owner_id
                and run.get('triggering_actor', {}).get('id') == cfg.owner_id
                and run.get('display_title') == 'foreign-issuer:' + request_digest(record, self.paths)
                and run.get('status') == status, 'ISSUER_RUN_MISMATCH')
        if status == 'completed':
            require(run.get('conclusion') == 'success', 'ISSUER_RUN_NOT_SUCCESSFUL')
        workflow = self.transport.get(self.root + '/contents/' + WORKFLOW,
                                      query={'ref': record.binding.central_revision})
        require(workflow.get('type') == 'file' and workflow.get('path') == WORKFLOW
                and workflow.get('sha') == cfg.workflow_blob, 'ISSUER_WORKFLOW_NOT_PINNED')
        reviews = self.transport.get(path + '/approvals')
        require(type(reviews) is list and len(reviews) == 1, 'ISSUER_APPROVAL_AMBIGUOUS')
        review = reviews[0]
        require(review.get('state') == 'approved' and review.get('user', {}).get('id') == cfg.owner_id
                and review.get('user', {}).get('type') == 'User'
                and review.get('comment') == self._approval_comment(record), 'ISSUER_APPROVAL_MISMATCH')
        envs = review.get('environments')
        require(type(envs) is list and len(envs) == 1
                and envs[0].get('id') == cfg.environment_id
                and envs[0].get('name') == cfg.environment
                and envs[0].get('can_admins_bypass') is False, 'ISSUER_ENVIRONMENT_UNVERIFIED')
        return run, review, workflow['sha']

    def verify_approval(self, record, evidence, *, now):
        try:
            from ..repository.legacy_work_identity import HistoryEvidence
            require(isinstance(evidence, HistoryEvidence)
                    and evidence.request.scope == record.binding.scope
                    and evidence.request.target_head == record.target_head
                    and sha256(canonical(asdict(evidence))).hexdigest() == record.history_digest,
                    'APPROVAL_HISTORY_MISMATCH')
            first = self._observe(record, status='in_progress')
            created = datetime.fromisoformat(first[0]['created_at'].replace('Z', '+00:00'))
            require(isinstance(now, datetime) and timedelta(0) <= now - created <= timedelta(hours=2),
                    'ISSUER_APPROVAL_EXPIRED')
            ref = self.transport.get(self.root + '/git/ref/heads/main')
            require(ref.get('ref') == 'refs/heads/main' and ref.get('object', {}).get('type') == 'commit'
                    and ref['object']['sha'] == record.binding.central_revision, 'ISSUER_MAIN_CHANGED')
            return self._observe(record, status='in_progress') == first
        except Exception:
            return False

    def verify_publication(self, record, commit, raw):
        """Independent post-run verification, suitable for ProtectedIssuanceStore.read_attestation."""
        try:
            first = self._observe(record, status='completed')
            run_id = self._run_id(record)
            path = self.root + '/actions/runs/' + str(run_id)
            jobs = self.transport.get(path + '/attempts/1/jobs', query={'per_page': '100'})
            require(type(jobs.get('jobs')) is list and jobs.get('total_count') == len(jobs['jobs']),
                    'ISSUER_JOBS_INCOMPLETE')
            matches = [j for j in jobs['jobs'] if j.get('name') == JOB]
            require(len(matches) == 1 and matches[0].get('run_id') == run_id
                    and matches[0].get('head_sha') == record.binding.central_revision
                    and matches[0].get('status') == 'completed' and matches[0].get('conclusion') == 'success',
                    'ISSUER_JOB_UNVERIFIED')
            steps = [s for s in matches[0].get('steps', []) if s.get('name') == STEP]
            require(len(steps) == 1 and steps[0].get('status') == 'completed'
                    and steps[0].get('conclusion') == 'success', 'ISSUER_PUBLICATION_STEP_UNVERIFIED')
            items = self.transport.get(path + '/artifacts', query={'per_page': '100'})
            require(type(items.get('artifacts')) is list and items.get('total_count') == len(items['artifacts']),
                    'ISSUER_ARTIFACTS_INCOMPLETE')
            matches = [x for x in items['artifacts'] if x.get('name') == f'foreign-issuance-{run_id}-1']
            require(len(matches) == 1, 'ISSUER_ARTIFACT_AMBIGUOUS')
            item = matches[0]
            require(type(item.get('id')) is int and item['id'] > 0 and item.get('expired') is False
                    and type(item.get('size_in_bytes')) is int and 0 < item['size_in_bytes'] <= 262144
                    and item.get('workflow_run', {}).get('id') == run_id, 'ISSUER_ARTIFACT_UNVERIFIED')
            archive = self.transport.artifact_zip(item['id'])
            require(type(archive) is bytes and 0 < len(archive) <= 262144
                    and len(archive) == item['size_in_bytes']
                    and item.get('digest') == 'sha256:' + sha256(archive).hexdigest(),
                    'ISSUER_ARTIFACT_DIGEST_MISMATCH')
            with ZipFile(BytesIO(archive)) as z:
                info = z.infolist()
                require(len(info) == 1 and info[0].filename == ARTIFACT_FILE
                        and 0 < info[0].file_size <= 65536, 'ISSUER_ARTIFACT_LAYOUT_MISMATCH')
                with z.open(info[0]) as f:
                    body = f.read(65537)
            expected = canonical(publication_receipt(record, commit, raw, self.paths))
            return (body == expected and self._observe(record, status='completed') == first
                    and self.transport.get(path + '/artifacts', query={'per_page': '100'}) == items)
        except Exception:
            return False
