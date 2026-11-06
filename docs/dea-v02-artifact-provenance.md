# DEA v0.2 — Artifact provenance and independent Fitness evidence

Owner-selected task: codeQA #288 phase-2 documentation-reference impact analysis.
Scope: READ-ONLY development on Samuel Draft PR #249. NO candidate branches,
workflow policy change, PR merge, champion, external API spend, or promotion.

## 1. Two independent source identities

- Candidate HEAD SHA: the exact commit to execute in a future Actions run.
- Analyzed source SHA: the pinned codeQA documentation/text snapshot that
  ALL A/B/C candidates analyze identically.

The codeQA common snapshot is not adopted yet, because PR #289 is unmerged.

## 2. Implemented evidence stages

A. dea_artifact_acquisition: read GET endpoints for GitHub Actions run, run
artifact list, and artifact ZIP; use a read-scoped token only on api.github.com.
Follow the presigned ZIP download redirect to trusted HTTPS storage **without**
forwarding the token. Bound response sizes. No dispatch/mutation.

B. dea_artifact_identity: verify exact repository, repository ID, run ID,
candidate HEAD, successful completed run, complete artifact listing,
unique numeric Artifact ID, name, non-expiration, SHA-256 digest, byte size,
and matching artifact workflow-run identity. Reject incomplete pagination.

C. verify_artifact_zip: independently check ZIP SHA-256 against GitHub metadata,
exact downloaded byte size, closed regular-file set, safe member names,
bounded inflation, strict UTF-8 JSON (no duplicate keys or non-finite values),
and internal file SHA-256 values. The expected ZIP contains exactly:
execution-manifest.json, observations.json, fitness-metrics.json and
validation-summary.json. The execution manifest has exact run/artifact IDs,
candidate HEAD, analyzed source SHA, Oracle SHA and measurement-protocol SHA,
plus three internal file SHA-256 digests.

D. dea_evidence_gate: correlate the run metadata (including workflow identity),
Artifact ZIP and exact local Git-object Oracle readback. Detect missing/forged
reference records. Ignore self-asserted PASS/Champion decisions inside the ZIP.

E. to_fitness_semantic_receipt: project the result to the v0.1 vector Fitness
contract. Only an independently observed semantic mismatch is FAIL; all other
statuses remain UNKNOWN while producer/job origin is not authenticated.
This ensures a fabricated high-performing candidate cannot be selected.

## 3. Explicitly unproved producer provenance

GitHub run-associated Artifact metadata cannot alone prove that a particular
trusted Job generated its contents from the expected source or with an honest
benchmark. A green CI run and a matching ZIP checksum are NOT sufficient.

Until a protected, independently verified producer/attestation workflow exists,
the result retains:

- producer_job_attribution: NOT_ATTESTED
- candidate_output_generation: NOT_ATTESTED
- workflow_integrity: NOT_ATTESTED
- runner_integrity: NOT_ATTESTED
- source_remote_ownership: NOT_ATTESTED
- pareto_eligible: false; champion: null; mutation_authorized: false

A perfect bounded Oracle match is BOUNDED_MATCH_PRODUCER_UNATTESTED.
Its Fitness semantic gate remains UNKNOWN. Even cryptographic provenance
does not establish meaning without the independent Oracle.

The current Samuel mutation policy explicitly denies .github/workflows/**
updates. This Draft PR deliberately leaves workflow YAML untouched. A
protected producer/validator workflow, job-to-artifact receipt, or signed
Artifact Attestation would require separate authorized integration and
verification; there is no implied approval to bypass those controls.

## 4. Security and test coverage

The existing CI unit suite executes synthetic end-to-end integration cases:
temporary source Git commits, fake GitHub run/artifact readbacks, in-memory
ZIPs and independent reference observations. Negative tests cover wrong
run/head/repo, expired/missing/duplicate artifacts, wrong ZIP digest,
tampered members, unsafe ZIP paths, missing or invalid JSON, NaN, forged
candidate PASS, external redirect targets, stale/unrelated inputs and
semantic mismatches.

This proves bounded control logic, not live production Artifact provenance.
No actual DEA A/B/C Artifact has yet been produced.

## 5. Manual read-only verification command (future real evidence only)

In an approved read-only environment, provide a scoped GH_TOKEN through the
environment. A local codeQA Git repository must contain the analyzed commit.

    PYTHONPATH=src python3 -m chatgpt_operation.controller.dea_artifact_acquisition \
      --repository HyungseonSong-plasma/codeQA \
      --workflow-path .github/workflows/APPROVED.yml \
      --candidate-head FULL_CANDIDATE_SHA \
      --analyzed-source-sha FULL_CODEQA_SOURCE_SHA \
      --oracle-revision-sha FULL_ORACLE_SHA \
      --measurement-set-sha FULL_MEASUREMENT_SHA \
      --source-repo-root /path/to/codeQA \
      --run-id REAL_RUN_ID --artifact-id REAL_ARTIFACT_ID \
      --artifact-name EXACT_ARTIFACT_NAME

Successful evidence readback is not admission to branch competition.

## 6. Still blocked

- codeQA PR #289 adoption and common codeQA Base SHA
- Complete required Markdown/known-consumer Oracle scope
- Trusted and independently attested artifact-producing Job
- Matching benchmark/compute budget and measured performance provenance
- Independent review and separate authority for a Champion/merge

The owner has conditionally approved v0.2 competition *after* these gates,
not prematurely authorized the A/B/C branches.
