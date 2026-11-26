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

from .ruleset_evidence import RULESET_ID, compare_snapshot


def observe(binding, *, snapshot=None, getter=get, clock=lambda: datetime.now(timezone.utc)):
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
    evidence = None
    if snapshot is not None:
        evidence = compare_snapshot(snapshot, rule, now=clock())
    # Snapshot comparison does not make an omitted live field observable.
    # Classify against the owner-attested snapshot only for this read-only
    # trial, with a distinct status that is not a live publication gate.
    snapshot_only = evidence is not None and not evidence['live_bypass_observable']
    reservation = plan_reservation(binding, current_main=main,
                                   ruleset=snapshot['ruleset'] if snapshot_only else rule,
                                   observed_ref=refs[0] if refs else None, observation_complete=True)
    if snapshot_only:
        reservation['status'] = 'SNAPSHOT_' + reservation['status']
    if evidence is not None:
        final_evidence = compare_snapshot(snapshot, getter(f'/rulesets/{RULESET_ID}'), now=clock())
        require(final_evidence == evidence, 'RULESET_OBSERVATION_CHANGED')
    require(getter('/branches/main')['commit']['sha'] == main, 'STALE_BASE')
    return {'status': 'LIVE_OBSERVATION_NON_AUTHORIZING', 'approval': approval,
            'reservation': reservation, 'ruleset_evidence': evidence,
            'write_authorized': False}
