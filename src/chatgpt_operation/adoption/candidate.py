"""Read-only candidate validation; no GitHub writes or authority grants.

The external trusted adoption service must authenticate the approval, collect
fresh repository evidence, and implement atomic publication separately.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Mapping

SHA = re.compile(r'[a-f0-9]{40}\Z')
HASH = re.compile(r'[a-f0-9]{64}\Z')
REGISTRY = 'skills/capability-registry.json'
CATALOG = 'skills/catalog.json'
README = 'skills/repository-mutation/README.md'
CONTRACT = 'skills/repository-mutation/checkpoint-cas-v0.1.md'
PATHS = frozenset((REGISTRY, CATALOG, README, CONTRACT))
CAPABILITY = 'GITHUB_CHECKPOINT_CAS'
ENTRY = {'providers': [{'name': 'github-connector', 'kind': 'external', 'priority': 10}],
         'exhaustion_policy': 'all_registered_providers_must_fail'}

class Hold(ValueError):
    pass

def require(condition, message):
    if not condition:
        raise Hold(message)

def digest(raw):
    return sha256(raw).hexdigest()

def unique(pairs):
    result = {}
    for k, v in pairs:
        require(k not in result, 'DUPLICATE_JSON_KEY')
        result[k] = v
    return result

def parse(raw):
    return json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(Hold('NONFINITE_JSON')))

def candidate_digest(base, changes):
    require(type(base) is str and SHA.fullmatch(base), 'BAD_BASE')
    require(set(changes) == PATHS, 'BAD_PATH_SCOPE')
    require(all(type(v) is bytes and 0 < len(v) <= 256000 for v in changes.values()), 'BAD_BYTES')
    manifest = {'repository':'HyungseonSong-plasma/chatgpt-operation','base_sha':base,
                'capability': CAPABILITY,'files':{p:digest(v) for p,v in sorted(changes.items())}}
    return digest(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode())

@dataclass(frozen=True)
class CandidateObservation:
    status: str
    candidate_sha256: str
    write_authorized: bool = False

def inspect_candidate(*, expected_base: str, observed_base: str,
                      baseline: Mapping[str, bytes], proposed: Mapping[str, bytes],
                      approved_candidate_sha256: str):
    """Compare an approval-bound payload; approval authenticity is OUTSIDE this function.

    Passing an arbitrary digest does not authenticate an owner. No method writes,
    dispatches, enrolls work, clears blockers or activates a registry.
    """
    require(expected_base == observed_base, 'STALE_BASE')
    actual = candidate_digest(expected_base, proposed)
    require(type(approved_candidate_sha256) is str and HASH.fullmatch(approved_candidate_sha256)
            and actual == approved_candidate_sha256, 'CANDIDATE_DIGEST_MISMATCH')
    require(set(baseline) == PATHS - {CONTRACT}, 'BASELINE_SCOPE_MISMATCH')
    old = parse(baseline[REGISTRY]); new = parse(proposed[REGISTRY])
    require(old.get('schema_version') == 1 and CAPABILITY not in old['capabilities'], 'REGISTRY_BASELINE_MISMATCH')
    old['capabilities'][CAPABILITY] = ENTRY
    require(json.dumps(new, sort_keys=True) == json.dumps(old, sort_keys=True), 'REGISTRY_DELTA_MISMATCH')
    old = parse(baseline[CATALOG]); new = parse(proposed[CATALOG])
    require(old.get('schema_version') == 1, 'CATALOG_BASELINE_MISMATCH')
    owners = [s for s in old['skills'] if s['name'] == 'repository-mutation']
    require(len(owners) == 1, 'CATALOG_OWNER_MISMATCH')
    for key in ('load_on', 'capabilities'):
        require(all(CAPABILITY not in s.get(key,[]) for s in old['skills']), 'DUPLICATE_TRIGGER')
        owners[0][key].append(CAPABILITY)
    # List ordering for these two sets is irrelevant; all other data must match.
    for c in (old,new):
        for s in c['skills']:
            if s['name'] == 'repository-mutation':
                for key in ('load_on','capabilities'):
                    require(len(s[key]) == len(set(s[key])), 'DUPLICATE_TRIGGER')
                    s[key].sort()
    require(json.dumps(new, sort_keys=True) == json.dumps(old, sort_keys=True), 'CATALOG_DELTA_MISMATCH')
    require(proposed[README].startswith(baseline[README]), 'README_REWRITE')
    return CandidateObservation('CANDIDATE_VALIDATED_NON_AUTHORIZING', actual)
