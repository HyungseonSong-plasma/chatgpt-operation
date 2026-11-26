import os
import subprocess
import unittest
from chatgpt_operation.adoption.approval import Binding
from chatgpt_operation.adoption.candidate import candidate_digest, REGISTRY
from chatgpt_operation.adoption.git_candidate import build_detached_candidate, verify_detached_commit
# The repository function-test runner loads files by absolute path without
# adding tests/ to sys.path. Load the sibling fixture by its exact file path
# so both unittest discovery and that runner use the same fixture.
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_fixture_spec = spec_from_file_location(
    '_adoption_git_request_fixture',
    Path(__file__).resolve().with_name('test_adoption_git_request.py'),
)
if _fixture_spec is None or _fixture_spec.loader is None:
    raise RuntimeError('cannot load adoption Git request fixture')
fixtures = module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(fixtures)


class DetachedCandidateTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.GitRequestTests(methodName='test_valid')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        f = self.fixture
        request = f.commit_request()
        f.git('checkout', '--detach', '-q', f.base)
        self.binding = Binding(f.base, request, candidate_digest(f.base, f.new), 123, 456)

    def test_detached_no_ref_or_worktree_change(self):
        f = self.fixture
        refs = f.git('show-ref')
        status = f.git('status', '--porcelain')
        receipt = build_detached_candidate(self.binding)
        self.assertFalse(receipt['write_authorized'])
        self.assertEqual(f.git('show-ref'), refs)
        self.assertEqual(f.git('status', '--porcelain'), status)
        self.assertEqual(f.git('rev-parse', 'HEAD'), f.base)
        self.assertEqual(verify_detached_commit(f.base, receipt['commit_sha'], f.new)['parents'], [f.base])

    def test_wrong_digest(self):
        b = self.binding
        with self.assertRaisesRegex(ValueError, 'CANDIDATE_DIGEST_MISMATCH'):
            build_detached_candidate(Binding(b.base, b.request_sha, '0'*64, b.run_id, b.environment_id))

    def test_wrong_parent(self):
        with self.assertRaisesRegex(ValueError, 'BAD_PARENT'):
            verify_detached_commit(self.binding.base, self.binding.base, self.fixture.new)

    def test_different_bytes(self):
        c = build_detached_candidate(self.binding)
        self.fixture.new[REGISTRY] = b'{}'
        with self.assertRaisesRegex(ValueError, 'BAD_FILE'):
            verify_detached_commit(self.binding.base, c['commit_sha'], self.fixture.new)

    def test_wrong_checkout(self):
        self.fixture.git('checkout', '--detach', '-q', self.binding.request_sha)
        with self.assertRaisesRegex(ValueError, 'STALE_CHECKOUT'):
            build_detached_candidate(self.binding)
