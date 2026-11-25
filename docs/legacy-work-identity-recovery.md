# Legacy work identity recovery — candidate v1

Baseline: Samuel `20827ec81ab0eac4dd7560a22ee4212e274113a5`.
Scope: read-only historical identity and coverage recovery. No permission grant, clearance, journal deployment, capability-registry change, or provider change.

## Problem

A previously active work package may have durable Issue/PR records but lack an accessible controller-issued work ID. An empty query result is not proof of a clean history, and an absent ID is not proof that no ID was issued. Conversely a missing history record is not itself an observed upstream denial. Preserve these distinctions in the preflight report.

## Contract

1. Trusted runtime reads immutable repository/Issue identities and the previously established bounded-work anchor. An Issue may contain multiple work packages; a PR is evidence of scope, not an independently issued work identity. A renamed branch or new PR must not establish new identity for the same work.
2. Recover the original controller-issued ID when present. Include all historical aliases, prior PRs/branches/providers and original denial sources in the coverage verifier. Preserve original evidence references and logical intent digests. Repository rename may change the old repository-name-based intent hash; cover both aliases, not only the new name.
3. When the original ID demonstrably was never issued, and only after verified scope and complete historical coverage, derive the deterministic `legacy-v1` candidate ID. The runtime must persist and authenticate that binding before treating it as enrolled. An unresolved or inaccessible ID cannot use this path.
4. Known blockers dominate incomplete coverage. `BLOCKER_PRESENT` does not mean every historical record is still active: send original evidence to existing Samuel blocker triage/clearance handling. This module does not reclassify or clear it.
5. Missing history is `HISTORY_INCOMPLETE`; missing scope or unresolved original identity is `IDENTITY_UNVERIFIED`. Neither is a discovered denial or authorization. Stop the affected mutation path and report the specific missing evidence instead of repeating identical queries.
6. `HISTORY_VERIFIED` is a read-only finding. The ordinary registered capability, policy, branch preflight, permissions, exact head and applicable CI still apply. Never treat this verdict as authorization. Do not bypass earlier safety screening, policy denials, or a configured CommonPreWriteGate.

No new always-on service or universal blocker journal is required by this candidate. Existing installed journal gates remain intact. An authenticated reader and coverage verifier are required; a model-supplied True, PR comment alone, or absent search result cannot establish coverage. For repeated preflight, durable verified evidence may be reused only within the same authenticated work scope, with refreshed mutable history and exact-head validation. Cache or persisted receipt implementation is out of scope.

## Consumer #908

`HyungseonSong-plasma/moose-test-repo` #888 / PR #908 at `1f6e7b86628ab6af6488a544453c785cc9590c2a` is a motivating example, not a fixture proving coverage. Prior D1/D2 readback says history was checked but does not supply original work identity or authoritative coverage source. No ID is generated for this case. Existing HOLD stays until trusted evidence is recovered; if unavailable, report exact missing source to the responsible authority. The proposed module has no live GitHub adapter and is not a production solution by itself.

## Verification

`PYTHONPATH=src python -m pytest -q tests/test_legacy_work_identity.py`

29 isolated tests pass. The module is self-contained and does not change the current blocker classifier or provider behavior. Full Samuel checkout, real adapter qualification, integration with the existing mutation skill and exact-head CI remain pending. This candidate is not committed, merged or adopted by the consumer.

S2 addendum: `legacy_github_history.py` adds the bounded read-only REST collector and S1 bridge; see `legacy-github-history-adapter.md` for qualification and the distinction between visible GitHub records and authoritative external history. The earlier S1 test count and status describe that earlier increment.
