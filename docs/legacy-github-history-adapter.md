# S2 — bounded GitHub history observation

Baseline Samuel: `20827ec81ab0eac4dd7560a22ee4212e274113a5`.

`legacy_github_history.GitHubHistoryReader` accepts a runtime-authenticated read-only REST JSON transport. It checks repository and issue immutable identities, current target PR HEAD, same-repository PRs, advertised issue/PR comment, review-comment and commit counts, duplicate IDs, terminal pagination and commit-tip identity. Reviews are paginated without an advertised count. Two independently collected canonical snapshots must agree. The reader binds the digest to the work anchor and target HEAD. GitHub's PR-commit endpoint is bounded at 250 commits; larger histories are rejected instead of silently truncated. The caller supplies a trusted inventory of historical PRs, which the collector cannot discover or certify on its own. Double collection is not an atomic snapshot or proof of immutability.

The `read_evidence` bridge invokes a trusted resolver, checks its request and source digest, and returns S1 `HistoryEvidence`. S1's independent scope and coverage verifiers are still mandatory. No free-text comment, zero result, model assertion, local file or this snapshot proves that no historical work ID was issued, that no external tool denial occurred, or that all historical PRs were enumerated. Known denials from authenticated sources must remain associated with the original identity. No change to provider order, blocker clearance, mutation permission, or central pin.

## Qualification

`PYTHONPATH=src python -m pytest -q tests`: 56 passed (29 S1, 27 S2). REST adapter exercised with in-memory fake responses, including count mismatch, wrong immutable identity, stale HEAD, fork, pagination overflow, duplicate records, edited comments, transport failure, missing coverage, malicious comment text and known blocker preservation. No full Samuel checkout or actual authenticated REST adapter run.

## Separate live connector observation — #908

Repository: `HyungseonSong-plasma/moose-test-repo`, repository ID 1346502851. Issue #888 ID 6592821787. PR #908 HEAD `1f6e7b86628ab6af6488a544453c785cc9590c2a`, base `8076102d957e658b69365315de434d76b76a92e1`. Two consecutive independent connector collections agreed on Issue/PR bodies, 3 Issue comments and 2 PR conversation comments (IDs 7158218615, 7158291674, 7158324151, 7165343653, 7165670549), and PR metadata reporting 5 commits. No explicit `work_id:` or `work ID=` value in the collected body/comment text. This was a separate connector probe, not execution of the new REST class, and did not enumerate all commit/review records. The prior D1/D2 statement that same-work history was checked does not supply its source or original ID. No external tool audit or authoritative enrollment record was recovered. Work scope binding and historical coverage remain unresolved; no new ID assigned and no write permitted.

## Next

Bind the existing authenticated transport and authoritative work-enrollment / original denial source to the S1 resolver; identify which source can actually attest original attempts and prior identities before writing a gate integration. If no such source is available, report the missing authority, not a clean result. Integration is blocked for #908 until this evidence is supplied or a legitimate owner-governed policy decision resolves the documentation requirement without overriding actual denials. No new global journal service is required. Full Samuel CI and explicit consumer pin adoption are still separate.
