"""Owner-attested Ruleset snapshot comparison. Never a live bypass proof.

GitHub may omit bypass_actors for callers without Ruleset write access.
The request SHA binds the snapshot to the owner's exact approval comment.
A request timestamp is a claim, not independently authenticated acquisition
time. Matching observable fields and updated_at is drift detection, not
proof that hidden policy is unchanged or that publication is authorized.
"""
from datetime import datetime, timedelta
from .candidate import require
from .reservation import verify_reservation_ruleset

RULESET_ID = 28142778
FIELDS = ('id', 'source', 'source_type', 'target', 'enforcement',
          'conditions', 'rules', 'updated_at')
SNAPSHOT_FIELDS = frozenset((*FIELDS, 'bypass_actors'))


def instant(value):
    require(type(value) is str, 'RULESET_BAD_TIME')
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('RULESET_BAD_TIME') from exc
    require(dt.tzinfo is not None and dt.utcoffset() is not None, 'RULESET_BAD_TIME')
    return dt


def compare_snapshot(snapshot, live, *, now):
    """Check claimed snapshot against live visible fields; fail closed on drift."""
    require(type(snapshot) is dict and set(snapshot) == {'schema_version', 'observed_at', 'ruleset'}
            and type(snapshot['schema_version']) is int and snapshot['schema_version'] == 1,
            'RULESET_SNAPSHOT_SCHEMA')
    rule = snapshot['ruleset']
    require(type(rule) is dict and set(rule) == SNAPSHOT_FIELDS
            and rule['id'] == RULESET_ID, 'RULESET_SNAPSHOT_SCOPE')
    verify_reservation_ruleset(rule)
    observed = instant(snapshot['observed_at'])
    version = instant(rule['updated_at'])
    require(version <= observed <= now and now - observed <= timedelta(hours=2),
            'RULESET_SNAPSHOT_STALE')
    require(type(live) is dict and all(k in live for k in FIELDS), 'RULESET_LIVE_FIELDS_MISSING')
    for k in FIELDS:
        if k == 'updated_at':
            require(instant(live[k]) == version, 'RULESET_VERSION_CHANGED')
        else:
            require(live[k] == rule[k], 'RULESET_VISIBLE_DRIFT')
    if 'bypass_actors' in live:
        require(live['bypass_actors'] == [], 'RESERVATION_BYPASS_UNKNOWN_OR_ENABLED')
        verify_reservation_ruleset(live)
        status = 'LIVE_BYPASS_EMPTY_NON_AUTHORIZING'
    else:
        status = 'SNAPSHOT_MATCHED_LIVE_BYPASS_UNOBSERVABLE'
    return {'status': status, 'ruleset_id': RULESET_ID,
            'snapshot_updated_at': rule['updated_at'],
            'snapshot_observed_at_claim': snapshot['observed_at'],
            'live_bypass_observable': 'bypass_actors' in live,
            'write_authorized': False}
