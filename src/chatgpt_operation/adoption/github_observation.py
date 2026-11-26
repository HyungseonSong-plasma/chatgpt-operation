"""Read-only GitHub evidence acquisition for the proposed adoption gateway.

No live writer. Uses the existing bounded fixed-origin GET transport. A missing
ref is represented only by an empty successful matching-refs collection; a
404, truncation or an ambiguous prefix response is not absence evidence.
"""
from datetime import datetime, timezone
from .approval import ENV, verify_approval
from .candidate import require
from .qualify import get, verify_environment
from .reservation import reservation_ref, plan_reservation

RULESET_ID = 28142778


def observe(binding, *, getter=get, clock=lambda: datetime.now(timezone.utc)):
    binding.validate()
    main = getter('/branches/main')['commit']['sha']
    env = getter('/environments/' + ENV)
    branches = getter('/environments/' + ENV + '/deployment-branch-policies')
    verify_environment(binding, env, branches)
    run = getter(f'/actions/runs/{binding.run_id}')
    reviews = getter(f'/actions/runs/{binding.run_id}/approvals')
    approval = verify_approval(binding, run=run, reviews=reviews, current_main=main, now=clock())
    rules = getter('/rulesets')
    require(type(rules) is list and sum(x.get('id') == RULESET_ID and x.get('enforcement') == 'active' for x in rules) == 1, 'RESERVATION_RULESET_NOT_LISTED')
    rule = getter(f'/rulesets/{RULESET_ID}')
    require(rule.get('id') == RULESET_ID, 'RESERVATION_RULESET_IDENTITY')
    expected = reservation_ref(binding)
    refs = getter('/git/matching-refs/' + expected.removeprefix('refs/'))
    require(type(refs) is list and len(refs) <= 1 and (not refs or refs[0].get('ref') == expected), 'AMBIGUOUS_REF_OBSERVATION')
    reservation = plan_reservation(binding, current_main=main, ruleset=rule,
                                   observed_ref=refs[0] if refs else None, observation_complete=True)
    require(getter('/branches/main')['commit']['sha'] == main, 'STALE_BASE')
    return {'status': 'LIVE_OBSERVATION_NON_AUTHORIZING', 'approval': approval,
            'reservation': reservation, 'write_authorized': False}
