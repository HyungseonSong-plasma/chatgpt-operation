"""Read-only binding of one environment approval to an immutable request.

Inputs are fresh authenticated GitHub GET responses supplied by the trusted runner.
No write authorization, replay ledger, environment administration, or provider calls.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from .candidate import SHA, HASH, require

REPO = 'HyungseonSong-plasma/chatgpt-operation'
REPO_ID = 1343601410
OWNER_ID = 189476866
ENV = 'samuel-registry-adoption'
WORKFLOW = '.github/workflows/samuel-adoption-qualification.yml'

@dataclass(frozen=True)
class Binding:
    base: str
    request_sha: str
    digest: str
    run_id: int
    environment_id: int

    def comment(self):
        return f'APPROVE {self.base} {self.request_sha} {self.digest} run:{self.run_id} attempt:1'

    def validate(self):
        require(all(type(x) is str and SHA.fullmatch(x) for x in (self.base,self.request_sha)), 'BAD_SHA')
        require(type(self.digest) is str and HASH.fullmatch(self.digest), 'BAD_DIGEST')
        require(all(type(x) is int and x > 0 for x in (self.run_id,self.environment_id)), 'BAD_ID')


def verify_approval(binding, *, run, reviews, current_main, now):
    binding.validate()
    require(current_main == binding.base, 'STALE_BASE')
    require(run.get('id') == binding.run_id and run.get('run_attempt') == 1
            and run.get('event') == 'workflow_dispatch' and run.get('path') == WORKFLOW
            and run.get('head_branch') == 'main' and run.get('head_sha') == binding.base
            and run.get('repository', {}).get('id') == REPO_ID
            and run.get('head_repository', {}).get('id') == REPO_ID
            and run.get('status') == 'in_progress'
            and run.get('display_title') == f'adoption:{binding.request_sha}:{binding.digest}', 'RUN_MISMATCH')
    try:
        created = datetime.fromisoformat(run['created_at'].replace('Z','+00:00'))
        age = now - created
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError('BAD_TIME') from exc
    require(timedelta(0) <= age <= timedelta(hours=2), 'EXPIRED_RUN')
    require(type(reviews) is list and len(reviews) == 1, 'AMBIGUOUS_APPROVAL')
    review = reviews[0]
    require(review.get('state') == 'approved' and review.get('user',{}).get('id') == OWNER_ID
            and review.get('user',{}).get('type') == 'User'
            and review.get('comment') == binding.comment(), 'APPROVAL_MISMATCH')
    environments = review.get('environments')
    require(type(environments) is list and len(environments) == 1
            and environments[0].get('id') == binding.environment_id
            and environments[0].get('name') == ENV, 'ENVIRONMENT_MISMATCH')
    return {'status':'APPROVAL_EVIDENCE_MATCHED_NON_AUTHORIZING', 'run_id':binding.run_id,
            'candidate_sha256':binding.digest, 'write_authorized':False}
