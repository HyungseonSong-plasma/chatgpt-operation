# DEA v0.2 — official Artifact producer / Sigstore Attestation adoption gate

**Status: REVIEWABLE IMPLEMENTATION CONTRACT ONLY; NOT DEPLOYED.**
**Owner intent:** retain invalid/missing/mismatched evidence for human review,
and proceed towards an officially authorized producing Job + Attestation.
**Authority:** Current Samuel repository mutation policy denies changes under
.github/workflows/**. This document does not change that policy or authorize
a different route. Competent authority must approve an eligible policy/
workflow adoption mechanism before a workflow is activated.

## What is implemented today

- Human-review packet: controller/dea_review_routing.py
  (HUMAN_REVIEW_REQUIRED, deterministic review ID, run/artifact links, problem
  category, evidence-preservation instruction, no automatic PASS).
- Read-only GitHub API fetch, Artifact metadata/ZIP checksum checks:
  controller/dea_artifact_acquisition.py, dea_artifact_identity.py.
- **v2 signable subject**: controller/dea_attested_payload.py and
  dea_payload_producer.py; deterministic dea-evidence.zip with four JSON
  members. Artifact ID intentionally absent before upload: it is assigned
  by GitHub after upload, and separately cross-checked by the verifier.
- GitHub/Sigstore cryptographic verifier: dea_attestation_verify.py, invoking
  gh attestation verify on the exact **inner payload bytes** with pinned
  expected repository, signer workflow/revision and source revision.
- Read-only bounded integration and review routing:
  controller/dea_attested_evidence_gate.py.

The **outer** GitHub Artifact download ZIP has its own SHA-256/digest, verified
against GitHub artifact metadata. The **inner** dea-evidence.zip is the
subject of the SLSA attestation. Never conflate those two byte streams or
attest the outer GitHub wrapper after it has been uploaded.

## Proposed official workflow — authority approval required

This is a security design, NOT an executable or adopted workflow.

1. **Candidate job**, untrusted/minimal permissions: check out the exact
   candidate source HEAD (not the pull request synthetic merge commit);
   analyze one independently pinned codeQA corpus, produce raw observations
   and metrics; do not give untrusted candidate code signing credentials or
   access to token-bearing trusted jobs.
2. **Trusted validator job**, using independently pinned Samuel verifier
   and frozen Oracle/profile: read back exact input and producer outputs,
   check source, test coverage and consistency; preserve malformed/failed
   inputs as a review packet. No invalid ZIP member is executed.
3. **Protected evidence producer/signing job**, after independent checks:
   generate deterministic dea-evidence.zip using the pre-upload v2 producer;
   sign **this exact file** using actions/attest@v4, subject-path set to
   dea-evidence.zip. The job needs GITHUB_TOKEN scopes:
   contents: read, id-token: write, attestations: write.
4. Upload **the same inner file** as a GitHub Actions Artifact with
   actions/upload-artifact@v7, path dea-evidence.zip, name unique to
   candidate and run, if-no-files-found: error. Capture its artifact-id and
   artifact-digest outputs *after* upload. Set appropriate finite retention.
5. **Independent consumer**: GET run metadata, full artifact list and ZIP,
   rehash outer ZIP, extract only the expected inner file, run
   gh attestation verify with --repo, --signer-workflow, --signer-digest,
   --source-digest, --deny-self-hosted-runners and --format json.
   Compare inner subject digest and exact bounded Git-object Oracle outputs.
   Verify the signed certificate and specific run/job relationship before
   recording producer provenance as fully attested.
6. Human-review delivery: publish review-packet IDs and GitHub readback links
   through an **authorized** issue/PR comment or dedicated review inbox;
   preserve original artifacts and do not rewrite/erase suspect evidence.
   If review confirms a defect or requests correction, produce a NEW run,
   new artifact ID/digest and rerun all gates.

A signing workflow MUST be protected from arbitrary modifications by
candidate branches. If a reusable workflow is used, pin its source commit
and require both caller and signer permissions according to GitHub's
official reusable-workflow guidance. Pin action SHAs after security review;
version tags below describe contracts, not immutable production pins.

## Non-deployable YAML shape (illustrative — do not copy to .github/workflows)

    permissions:
      contents: read
      id-token: write
      attestations: write

    steps:
      - name: Create signed subject
        run: python3 -m chatgpt_operation.controller.dea_payload_producer ...
      - name: Attest exact subject (pin action commit in real workflow)
        uses: actions/attest@v4
        with:
          subject-path: dea-evidence.zip
      - name: Upload the same file (pin action commit in real workflow)
        id: upload
        uses: actions/upload-artifact@v7
        with:
          name: dea-candidate-evidence-UNIQUE
          path: dea-evidence.zip
          if-no-files-found: error

The example does not supply all required pinned arguments, trusted checkout,
job/runner restrictions or artifacts handoff. It is deliberately **not
deployable as-is**.

## Human review rather than destructive rejection

An incorrect run, expired/missing artifact, altered digest, incomplete ZIP,
unsafe archive member, unsupported record or failed Attestation yields
HUMAN_REVIEW_REQUIRED with exact referenced candidate/run/artifact identities
when known. Evidence is not automatically deleted, and unsafe bytes are
quarantined from execution. A human may request a fresh run, inspect the
original artifact, confirm an observed defect or request separate scoped
policy authority. Review does not magically make the bytes valid; a
revalidated corrected artifact must be introduced via new evidence identity.

The current module generates a review packet but does NOT itself deliver
a notification to a human mailbox/issue. That delivery needs a separately
approved controller workflow/inbox integration.

## Final authorization gates

- Formal owner/policy authority for workflow changes, not an alternate Git API.
- Adopted codeQA PR #289 exact base SHA and accepted scope of semantic Oracle.
- Protected runner/workflow identities, version/commit pinning, verified
  GitHub Artifact Attestation and run/job-to-artifact attribution.
- Complete human review routing/retention and independent code review.
- Identical A/B/C budgets and measured benchmarks; separate human Champion gate.

Until these gates are complete: no new A/B/C branches, no workflow dispatch,
no PR merge and no claim of end-to-end producer certification.

Official references:
- https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations
- https://docs.github.com/en/actions/concepts/security/artifact-attestations
- https://cli.github.com/manual/gh_attestation_verify
- https://github.com/actions/upload-artifact
