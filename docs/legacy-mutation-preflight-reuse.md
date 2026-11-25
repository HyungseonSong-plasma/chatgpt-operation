# S3–S4 — read-only mutation history preflight and optional reuse

Baseline `20827ec81ab0eac4dd7560a22ee4212e274113a5`. The accompanying `qualification/repository-mutation-skill.patch` adds a candidate routing paragraph to the exact pinned skill (original blob `9d49125e10b293b5c3fe7adc38ff3b9f5c020608`). The code and patch are local candidates, not an adopted skill or deployed mutation gate.

## S3: use the read-only result before ordinary branch preflight

`legacy_mutation_preflight.observe_history` composes the S1 recovery result; `observe_github_history` connects S2's authenticated REST collector and trusted resolver. No provider call is exposed.

| Recovery | Disposition |
|---|---|
| IDENTITY_UNVERIFIED | RESTORE_IDENTITY |
| HISTORY_INCOMPLETE | RESTORE_COVERAGE |
| BLOCKER_PRESENT | EXISTING_BLOCKER_GATE (original evidence remains intact) |
| HISTORY_VERIFIED | CONTINUE_ORDINARY_PREFLIGHT |

All outputs have `mutation_authorized=False`. A verified legacy-derived ID remains a candidate until authenticated enrollment. Existing configured CommonPreWriteGate, blocker triage/clearance, branch preflight, exact HEAD, policy, permissions, current CI and applicable review are unchanged. The connector-only routing rules remain unchanged. The bridge is not wired into every provider, CLI, or production runner. The skill patch documents the intended caller integration only.

## S4: bounded reuse, no mandatory new service

`VerifiedHistoryReuse` holds one in-memory positive observation in a trusted runtime. It requires a fresh authenticated `HistoryVersion` before reuse, bound to the exact request (repository, issue, work anchor, HEAD), central pin, trusted authority, generation and canonical digest of complete evidence. A full read compares versions before and after verification and checks the evidence digest. Changed generation, scope, HEAD, authority, pin, digest, incomplete history or revocation reflected in the authoritative version invalidates reuse. Known blockers are never cached as clean. If the optional version probe is unavailable, discard the cache and run ordinary full verification; if a version changes during a full verified read, return HISTORY_INCOMPLETE rather than a positive result. Failed or incomplete observations are not reused.

The probe must actually observe the authenticated complete enrollment/alias/denial/clearance source and verifier revocation status, including non-GitHub sources. Its generation must be rollback-resistant in the authority's domain. Merely reading GitHub HEAD, calculating a comment hash, using a TTL, or replaying a local file cannot substitute. A matching version is not a mutation-time lock or atomic transaction. This module provides no durable receipt store or cross-runner cache; fresh processes reverify. No production probe has been provisioned. Do not construct one from model-supplied evidence.

## Verification and remaining scope

`PYTHONPATH=src python -m pytest -q tests`: 88 passed (56 S1–S2, 12 S3, 20 S4). S3 tests exercise the fake REST collector end-to-end and preserve original blocker records; S4 verifies full-read/verification counts, cache invalidation, version drift, digest mismatch and revoked coverage. All history transports, authorities and version probes in these tests are test doubles. No full Samuel checkout, live authoritative history version, production route integration, remote commit, CI, or consumer pin adoption.

For #908, S2's live connector observations remain incomplete for identity and external history. The new module will not infer absence of an original ID or tool denial from those observations. S5 requires a legitimate source of trusted work binding and prior same-work records, or a separately governed policy decision about what historical evidence suffices (without clearing or bypassing an actual denial). The optional version cache is not the prerequisite for S5. Do not repeat identical GitHub searches as a substitute for missing authority. No Controller activation or merge authority is implied.
