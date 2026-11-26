"""Read-only contract for a prospective immutable publication reservation.

No GitHub writes. Ruleset observations must come from authenticated, complete
fresh reads by an independently authorized runtime. A plan is not authority.
The proposed namespace needs owner-provisioned no-update/no-delete protection.
"""
from .approval import REPO, Binding
from .candidate import SHA, require

NAMESPACE = 'refs/heads/samuel/adoption-reservations/'
PATTERN = NAMESPACE + '*'

def verify_reservation_ruleset(rule):
    require(type(rule) is dict and rule.get('source_type') == 'Repository'
            and rule.get('source') == REPO and rule.get('target') == 'branch'
            and rule.get('enforcement') == 'active', 'RESERVATION_RULESET_IDENTITY')
    require(rule.get('conditions') == {'ref_name': {'include': [PATTERN], 'exclude': []}},
            'RESERVATION_RULESET_SCOPE')
    require(rule.get('bypass_actors') == [], 'RESERVATION_BYPASS_UNKNOWN_OR_ENABLED')
    rules = rule.get('rules')
    require(type(rules) is list and all(type(x) is dict for x in rules)
            and sorted(x.get('type','') for x in rules) == ['deletion','update'],
            'RESERVATION_NOT_IMMUTABLE')
    return True

def reservation_ref(binding: Binding):
    binding.validate()
    return NAMESPACE + binding.digest

def plan_reservation(binding, *, current_main, ruleset, observed_ref, observation_complete):
    """Classify an authenticated ref read. Absence is not a lease or a lock."""
    verify_reservation_ruleset(ruleset)
    require(current_main == binding.base, 'STALE_BASE')
    require(observation_complete is True, 'INCOMPLETE_REF_OBSERVATION')
    ref = reservation_ref(binding)
    if observed_ref is not None:
        require(type(observed_ref) is dict and observed_ref.get('ref') == ref
                and type(observed_ref.get('object')) is dict
                and observed_ref['object'].get('type') == 'commit'
                and type(observed_ref['object'].get('sha')) is str
                and SHA.fullmatch(observed_ref['object']['sha']), 'INVALID_REF_OBSERVATION')
        status = 'RESERVATION_EXISTS_RECONCILE_ONLY'
    else:
        status = 'RESERVATION_ABSENT_NON_AUTHORIZING'
    return {'status':status, 'ref':ref, 'candidate_digest':binding.digest,
            'write_authorized':False}
