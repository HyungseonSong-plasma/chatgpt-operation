"""Concrete GitHub authority wire-format tests, no production writes."""
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import unittest
from zipfile import ZipFile

from chatgpt_operation.controller.foreign_issuer_authority import (
    ARTIFACT_FILE, JOB, STEP, WORKFLOW, GitHubIssuerAuthority, IssuerAuthorityConfig,
    publication_receipt, request_digest,
)
from chatgpt_operation.controller.foreign_work_issuer import FirstIssuance, canonical

ROOT = '/repos/example/samuel'
RUN = ROOT + '/actions/runs/42'
WORKFLOW_BLOB = 'f' * 40
COMMIT = 'e' * 40
NOW = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)


class Transport:
    def __init__(self):
        self.responses = {}
        self.archive = b''
        self.reads = []

    def get(self, path, *, query=None):
        self.reads.append((path, query))
        return deepcopy(self.responses[path])

    def artifact_zip(self, artifact_id):
        if artifact_id != 73:
            raise ValueError('unknown artifact')
        return self.archive


class TestGitHubIssuerAuthority(unittest.TestCase):
    def setUp(self):
        from test_foreign_init_runtime import Scenario, PATHS
        s = Scenario()
        self.paths = PATHS
        self.history = replace(s.history, original_work_id=None,
                               historical_work_ids=(), no_original_id_issued=True)
        self.record = FirstIssuance(s.binding, self.history.request.target_head,
            sha256(canonical(asdict(self.history))).hexdigest(),
            'github-environment:31:run:42:1', 'github-actions-run:42:1')
        self.raw = canonical(self.record.payload(self.paths))
        self.transport = Transport()
        self.authority = GitHubIssuerAuthority(
            config=IssuerAuthorityConfig('example/samuel', 21, 19, 31,
                                         'samuel-foreign-issuer', WORKFLOW_BLOB),
            transport=self.transport, paths=self.paths)
        digest = request_digest(self.record, self.paths)
        self.transport.responses = {
            ROOT: {'id': 21, 'full_name': 'example/samuel'},
            RUN: {'id': 42, 'run_attempt': 1, 'event': 'workflow_dispatch',
                  'path': WORKFLOW, 'head_branch': 'main',
                  'head_sha': self.record.binding.central_revision,
                  'repository': {'id': 21}, 'head_repository': {'id': 21},
                  'actor': {'id': 19}, 'triggering_actor': {'id': 19},
                  'display_title': 'foreign-issuer:' + digest, 'status': 'in_progress',
                  'created_at': (NOW - timedelta(minutes=1)).isoformat()},
            ROOT + '/contents/' + WORKFLOW: {'type': 'file', 'path': WORKFLOW, 'sha': WORKFLOW_BLOB},
            RUN + '/approvals': [{'state': 'approved', 'user': {'id': 19, 'type': 'User'},
                'comment': 'APPROVE FOREIGN ISSUANCE ' + digest + ' payload:' +
                           sha256(self.raw).hexdigest() + ' run:42 attempt:1',
                'environments': [{'id': 31, 'name': 'samuel-foreign-issuer', 'can_admins_bypass': False}]}],
            ROOT + '/git/ref/heads/main': {'ref': 'refs/heads/main',
                'object': {'type': 'commit', 'sha': self.record.binding.central_revision}},
            RUN + '/attempts/1/jobs': {'total_count': 1, 'jobs': [
                {'name': JOB, 'run_id': 42, 'head_sha': self.record.binding.central_revision,
                 'status': 'completed', 'conclusion': 'success',
                 'steps': [{'name': STEP, 'status': 'completed', 'conclusion': 'success'}]}]},
        }
        self.set_archive(canonical(publication_receipt(self.record, COMMIT, self.raw, self.paths)))

    def set_archive(self, body, name=ARTIFACT_FILE):
        buf = BytesIO()
        with ZipFile(buf, 'w') as z:
            z.writestr(name, body)
        self.transport.archive = buf.getvalue()
        self.transport.responses[RUN + '/artifacts'] = {
            'total_count': 1, 'artifacts': [{'id': 73, 'name': 'foreign-issuance-42-1',
                'expired': False, 'size_in_bytes': len(self.transport.archive),
                'workflow_run': {'id': 42},
                'digest': 'sha256:' + sha256(self.transport.archive).hexdigest()}]}

    def approve(self, record=None, evidence=None, now=NOW):
        return self.authority.verify_approval(
            self.record if record is None else record,
            self.history if evidence is None else evidence, now=now)

    def completed(self):
        self.transport.responses[RUN].update(status='completed', conclusion='success')

    def publish(self, record=None, commit=COMMIT, raw=None):
        return self.authority.verify_publication(
            self.record if record is None else record, commit,
            self.raw if raw is None else raw)

    def test_exact_owner_approval(self):
        self.assertTrue(self.approve())
        self.assertIn((ROOT + '/contents/' + WORKFLOW,
                       {'ref': self.record.binding.central_revision}), self.transport.reads)

    def test_completed_publication_matches_receipt(self):
        self.completed()
        self.assertTrue(self.publish())
        self.assertFalse(self.approve())

    def test_in_progress_not_completed_publication(self):
        self.assertFalse(self.publish())

    def test_history_bound_to_approval(self):
        self.assertFalse(self.approve(evidence=replace(self.history, source_ref='different')))

    def test_stale_head_and_expired_approval(self):
        self.assertFalse(self.approve(now=NOW + timedelta(hours=3)))
        self.transport.responses[ROOT + '/git/ref/heads/main']['object']['sha'] = '0' * 40
        self.assertFalse(self.approve())

    def test_replay_and_wrong_run_identity(self):
        for key, value in [('run_attempt', 2), ('event', 'push'), ('head_branch', 'other'),
                           ('head_sha', '0' * 40), ('triggering_actor', {'id': 99}),
                           ('actor', {'id': 99}), ('head_repository', {'id': 99}),
                           ('display_title', 'foreign-issuer:wrong')]:
            with self.subTest(key=key):
                before = self.transport.responses[RUN][key]
                self.transport.responses[RUN][key] = value
                self.assertFalse(self.approve())
                self.transport.responses[RUN][key] = before

    def test_unpinned_workflow(self):
        self.transport.responses[ROOT + '/contents/' + WORKFLOW]['sha'] = '0' * 40
        self.assertFalse(self.approve())

    def test_approval_comment_exact(self):
        self.transport.responses[RUN + '/approvals'][0]['comment'] += ' extra'
        self.assertFalse(self.approve())

    def test_wrong_reviewer(self):
        self.transport.responses[RUN + '/approvals'][0]['user']['id'] = 99
        self.assertFalse(self.approve())

    def test_duplicate_approval(self):
        reviews = self.transport.responses[RUN + '/approvals']
        reviews.append(deepcopy(reviews[0]))
        self.assertFalse(self.approve())

    def test_admin_bypass_unknown_or_enabled(self):
        env = self.transport.responses[RUN + '/approvals'][0]['environments'][0]
        env.pop('can_admins_bypass')
        self.assertFalse(self.approve())
        env['can_admins_bypass'] = True
        self.assertFalse(self.approve())

    def test_unbound_run_ref(self):
        self.assertFalse(self.approve(record=replace(self.record, publisher_ref='github-actions-run:42:2')))
        self.assertFalse(self.approve(record=replace(self.record, approval_ref='other')))

    def test_failed_job_or_step(self):
        self.completed()
        job = self.transport.responses[RUN + '/attempts/1/jobs']['jobs'][0]
        job['steps'][0]['conclusion'] = 'skipped'
        self.assertFalse(self.publish())
        job['steps'][0]['conclusion'] = 'success'
        job['conclusion'] = 'failure'
        self.assertFalse(self.publish())

    def test_incomplete_job_or_artifact_census(self):
        self.completed()
        jobs = self.transport.responses[RUN + '/attempts/1/jobs']
        jobs['total_count'] = 2
        self.assertFalse(self.publish())
        jobs['total_count'] = 1
        self.transport.responses[RUN + '/artifacts']['total_count'] = 2
        self.assertFalse(self.publish())

    def test_expired_or_unbound_artifact(self):
        self.completed()
        item = self.transport.responses[RUN + '/artifacts']['artifacts'][0]
        item['expired'] = True
        self.assertFalse(self.publish())
        item['expired'] = False
        item['workflow_run']['id'] = 99
        self.assertFalse(self.publish())

    def test_archive_digest_mismatch(self):
        self.completed()
        self.transport.responses[RUN + '/artifacts']['artifacts'][0]['digest'] = 'sha256:' + '0' * 64
        self.assertFalse(self.publish())

    def test_exact_receipt_payload_and_commit(self):
        self.completed()
        self.assertFalse(self.publish(commit='0' * 40))
        self.assertFalse(self.publish(raw=b'{}'))
        self.set_archive(b'{}')
        self.assertFalse(self.publish())

    def test_zip_layout_refused(self):
        self.completed()
        self.set_archive(self.raw, name='../issuance-receipt.json')
        self.assertFalse(self.publish())

    def test_source_failure_fails_closed(self):
        self.transport.responses.pop(RUN)
        self.assertFalse(self.approve())
        self.assertFalse(self.publish())

    def test_drift_between_reads_fails_closed(self):
        original = self.transport.get
        calls = 0
        def changing(path, *, query=None):
            nonlocal calls
            value = original(path, query=query)
            if path == RUN:
                calls += 1
                if calls == 2:
                    value['updated_at'] = 'changed'
            return value
        self.transport.get = changing
        self.assertFalse(self.approve())


if __name__ == '__main__':
    unittest.main()
