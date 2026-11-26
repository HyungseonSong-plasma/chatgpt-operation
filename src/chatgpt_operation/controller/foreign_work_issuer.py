"""Create-once foreign Work issuance, separate from Journal enrollment.

Only a trusted repository-native composition root may supply authenticated
history, owner approval, lease, ruleset, current-head and provenance ports.
The existing domestic ledger is unchanged. No enrollment or clearance here.
"""
from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
from hashlib import sha1, sha256
import json
import re

from .foreign_work_admission import ForeignAdmissionBinding, EnrollmentRecord
from .foreign_enrollment_contract import ForeignEnrollmentAttestation, IntentRegistration, ForeignEnrollmentAuthority
from .foreign_issuance import IssuanceHold, require
from ..repository.legacy_work_identity import HistoryEvidence, RecoveryRequest, recover_work_identity, RecoveryStatus
from ..repository.blocker_triage import logical_intent_id

PREFIX = 'refs/heads/samuel/journal-anchors/issuance-'
FILENAME = 'work-issuance.json'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')


def issuance_ref(scope):
    # Stable across repository rename, target branch, target HEAD and retries.
    return PREFIX + scope.legacy_work_id().split(':', 1)[1]


def valid_sha(value):
    return isinstance(value, str) and bool(re.fullmatch(r'[0-9a-f]{40}', value))


@dataclass(frozen=True)
class FirstIssuance:
    binding: ForeignAdmissionBinding
    target_head: str
    history_digest: str
    approval_ref: str
    publisher_ref: str

    def __post_init__(self):
        require(isinstance(self.binding, ForeignAdmissionBinding) and valid_sha(self.target_head)
                and isinstance(self.history_digest, str) and bool(re.fullmatch(r'[0-9a-f]{64}', self.history_digest))
                and all(isinstance(x, str) and bool(x) and x == x.strip()
                        for x in (self.approval_ref, self.publisher_ref)), 'INVALID_ISSUANCE_RECORD')

    @property
    def ref(self):
        return issuance_ref(self.binding.scope)

    def attestation(self, paths):
        scope = self.binding.scope
        work_id = scope.legacy_work_id()
        record = EnrollmentRecord(scope, work_id, (work_id,), self.binding.issuer_id, self.ref)
        intent = logical_intent_id(repository=scope.repository, branch=self.binding.target_branch,
                                   work_id=work_id, paths=paths)
        return ForeignEnrollmentAttestation(record, self.binding.central_revision, 1, self.ref,
                                            (IntentRegistration(scope.repository, work_id, intent, self.ref),))

    def payload(self, paths):
        return {'schema': 'samuel.foreign-work-issuance.v1', 'issuance': asdict(self),
                'attestation': asdict(self.attestation(paths)),
                'work_enrolled': False, 'controller_execution_approved': False}


class ProtectedIssuanceStore:
    """GitHub create-only object/ref storage using an authenticated transport.

    A protected ref is storage, not authority: readers must also authenticate
    publisher provenance and revocation. No update/delete or fallback route.
    """
    def __init__(self, *, repository, repository_id, transport):
        require(isinstance(repository, str) and bool(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository))
                and type(repository_id) is int and repository_id > 0
                and callable(getattr(transport, 'get', None))
                and callable(getattr(transport, 'post', None)), 'INVALID_ISSUER_STORE')
        self.root, self.repo_id, self.transport = '/repos/' + repository, repository_id, transport

    def _identity(self):
        repo = self.transport.get(self.root)
        require(repo.get('id') == self.repo_id and repo.get('full_name') == self.root[7:],
                'ISSUER_REPOSITORY_MISMATCH')

    def _ref(self, ref):
        self._identity()
        require(bool(re.fullmatch(re.escape(PREFIX) + r'[0-9a-f]{64}', ref)), 'INVALID_ISSUANCE_REF')
        rows = self.transport.get(self.root + '/git/matching-refs/' + ref.removeprefix('refs/'))
        require(isinstance(rows, list) and len(rows) <= 1, 'AMBIGUOUS_ISSUANCE_REF')
        if not rows:
            return None
        obj = rows[0].get('object', {})
        require(rows[0].get('ref') == ref and obj.get('type') == 'commit' and valid_sha(obj.get('sha')),
                'ISSUANCE_REF_MISMATCH')
        return obj['sha']

    def read(self, ref):
        commit = self._ref(ref)
        if commit is None:
            return None
        c = self.transport.get(self.root + '/git/commits/' + commit)
        tree = c.get('tree', {}).get('sha')
        require(c.get('sha') == commit and c.get('parents') == [] and valid_sha(tree),
                'ISSUANCE_COMMIT_MISMATCH')
        t = self.transport.get(self.root + '/git/trees/' + tree)
        entries = t.get('tree')
        require(t.get('sha') == tree and t.get('truncated') is False and isinstance(entries, list)
                and len(entries) == 1, 'ISSUANCE_TREE_MISMATCH')
        entry = entries[0]
        blob = entry.get('sha')
        require(entry.get('path') == FILENAME and entry.get('mode') == '100644'
                and entry.get('type') == 'blob' and valid_sha(blob), 'ISSUANCE_BLOB_MISMATCH')
        item = self.transport.get(self.root + '/git/blobs/' + blob)
        require(item.get('sha') == blob and item.get('encoding') == 'base64', 'ISSUANCE_BLOB_UNREADABLE')
        raw = base64.b64decode(''.join(item['content'].split()), validate=True)
        require(len(raw) <= 65536 and item.get('size') == len(raw)
                and sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == blob,
                'ISSUANCE_CONTENT_MISMATCH')
        data = json.loads(raw)
        require(canonical(data) == raw and self._ref(ref) == commit, 'ISSUANCE_CHANGED_OR_NONCANONICAL')
        return commit, raw

    def create_once(self, *, ref, raw, before_write):
        require(isinstance(raw, bytes) and len(raw) <= 65536 and canonical(json.loads(raw)) == raw,
                'INVALID_ISSUANCE_PAYLOAD')
        require(self.read(ref) is None, 'ISSUANCE_EXISTS_RECONCILE_ONLY')

        def post(path, payload):
            require(before_write() is True, 'ISSUER_BOUNDARY_CHANGED')
            result = self.transport.post(self.root + path, payload)
            require(isinstance(result, dict), 'UNKNOWN_ISSUANCE_PUBLICATION')
            return result

        expected = sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        blob = post('/git/blobs', {'content': base64.b64encode(raw).decode(), 'encoding': 'base64'}).get('sha')
        require(blob == expected, 'ISSUANCE_BLOB_WRITE_MISMATCH')
        tree = post('/git/trees', {'tree': [{'path': FILENAME, 'mode': '100644', 'type': 'blob', 'sha': blob}]}).get('sha')
        require(valid_sha(tree), 'ISSUANCE_TREE_WRITE_MISMATCH')
        commit = post('/git/commits', {'message': 'Samuel immutable Work issuance', 'tree': tree, 'parents': []}).get('sha')
        require(valid_sha(commit) and self.read(ref) is None, 'ISSUANCE_EXISTS_OR_COMMIT_INVALID')
        result = post('/git/refs', {'ref': ref, 'sha': commit})
        require(result.get('ref') == ref and result.get('object', {}).get('sha') == commit
                and self.read(ref) == (commit, raw), 'ISSUANCE_READBACK_FAILED')
        return commit


def issue_first(*, binding, request, store, paths, approval_ref, publisher_ref,
                read_history, verify_scope, verify_coverage, verify_approval,
                verify_lease, verify_ruleset, read_head, verify_publication):
    """Persist a verified first issuance; never repair or replace a prior ID.

    History completeness and the original no-issuance assertion must come
    from the responsible authority, not a negative ledger search. A known
    blocker with no original identity remains HOLD for separate reconciliation.
    On uncertain publication do not replay: reconcile the existing ref.
    """
    require(isinstance(binding, ForeignAdmissionBinding) and isinstance(request, RecoveryRequest)
            and request.scope == binding.scope and isinstance(store, ProtectedIssuanceStore),
            'ISSUER_SCOPE_MISMATCH')
    evidence = read_history(request)
    require(isinstance(evidence, HistoryEvidence) and evidence.request == request
            and evidence.no_original_id_issued is True and not evidence.blockers,
            'FIRST_ISSUANCE_NOT_PROVEN')
    recovered = recover_work_identity(request, trusted_reader=lambda _: evidence,
                                     verify_scope=verify_scope, verify_coverage=verify_coverage)
    require(recovered.status is RecoveryStatus.HISTORY_VERIFIED
            and recovered.work_id == binding.scope.legacy_work_id(), 'FIRST_ISSUANCE_HISTORY_UNVERIFIED')
    record = FirstIssuance(binding, request.target_head, sha256(canonical(asdict(evidence))).hexdigest(),
                           approval_ref, publisher_ref)
    raw = canonical(record.payload(paths))

    def current():
        return (verify_lease() is True and verify_ruleset() is True
                and read_head() == request.target_head and read_history(request) == evidence
                and verify_scope(evidence) is True and verify_coverage(evidence) is True
                and verify_approval(record, evidence) is True)

    require(current() is True, 'ISSUER_BOUNDARY_UNVERIFIED')
    commit = store.create_once(ref=record.ref, raw=raw, before_write=current)
    require(current() is True and verify_publication(record, commit, raw) is True
            and store.read(record.ref) == (commit, raw), 'ISSUANCE_PROVENANCE_UNVERIFIED')
    return record, commit
