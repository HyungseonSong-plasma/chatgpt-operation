"""Build and verify a detached candidate in a disposable local Git repository.

No network, ref mutation, checkout of request data or remote publication.
A successful result is content evidence, not authority to publish.
"""
import os
import subprocess
import tempfile
from pathlib import Path
from .candidate import PATHS, CONTRACT, SHA, inspect_candidate, require
from .qualify import read_blob, candidate_from_git


def _git(*args, data=None, env=None):
    return subprocess.check_output(['git', *args], input=data, env=env, timeout=30)


def _sha(raw):
    value = raw.decode('ascii').strip()
    require(SHA.fullmatch(value), 'INVALID_GIT_OBJECT')
    return value


def verify_detached_commit(base, commit, proposed):
    require(SHA.fullmatch(base) and SHA.fullmatch(commit), 'BAD_SHA')
    require(set(proposed) == PATHS, 'BAD_PATH_SCOPE')
    require(_git('rev-list', '--parents', '-n', '1', commit).decode().split() == [commit, base], 'BAD_PARENT')
    records = _git('diff-tree', '--no-commit-id', '--name-status', '--no-renames', '-r', '-z', base, commit).split(b'\0')
    require(records[-1] == b'' and len(records) == 2 * len(PATHS) + 1, 'BAD_DIFF')
    changes = dict(zip(records[1:-1:2], records[:-1:2]))
    require(changes == {p.encode(): b'A' if p == CONTRACT else b'M' for p in PATHS}, 'BAD_DIFF')
    for p, content in proposed.items():
        require(read_blob(commit, p) == content, 'BAD_FILE')
    return {'sha': commit, 'parents': [base], 'complete': True,
            'files': {p: {'mode': '100644', 'bytes': v} for p, v in proposed.items()}}


def build_detached_candidate(binding):
    """Read a data-only request and construct exactly one local child commit.

    The working tree and all refs remain unchanged; a temporary Git index is
    used. Call only in an isolated trusted checkout without write credentials.
    """
    binding.validate()
    require(_sha(_git('rev-parse', 'HEAD')) == binding.base, 'STALE_CHECKOUT')
    baseline, proposed = candidate_from_git(binding.base, binding.request_sha)
    inspect_candidate(expected_base=binding.base, observed_base=binding.base,
                      baseline=baseline, proposed=proposed,
                      approved_candidate_sha256=binding.digest)
    with tempfile.TemporaryDirectory(prefix='adoption-index-') as d:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(d) / 'index'),
                   GIT_AUTHOR_NAME='Samuel Adoption Candidate', GIT_AUTHOR_EMAIL='adoption@invalid',
                   GIT_COMMITTER_NAME='Samuel Adoption Candidate', GIT_COMMITTER_EMAIL='adoption@invalid')
        _git('read-tree', binding.base, env=env)
        for path, content in sorted(proposed.items()):
            blob = _sha(_git('hash-object', '-w', '--stdin', data=content, env=env))
            _git('update-index', '--add', '--cacheinfo', '100644', blob, path, env=env)
        tree = _sha(_git('write-tree', env=env))
        message = f'Adoption candidate {binding.digest}\n\nRequest {binding.request_sha}\nRun {binding.run_id} attempt 1\n'
        commit = _sha(_git('commit-tree', tree, '-p', binding.base, data=message.encode(), env=env))
    verify_detached_commit(binding.base, commit, proposed)
    require(_sha(_git('rev-parse', 'HEAD')) == binding.base, 'STALE_CHECKOUT')
    return {'status': 'DETACHED_CANDIDATE_VERIFIED_NON_AUTHORIZING',
            'commit_sha': commit, 'tree_sha': tree, 'candidate_digest': binding.digest,
            'write_authorized': False}
