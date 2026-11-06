# Issue #254 — Human-controlled Producer Workflow adoption handoff

**Status:** OWNER ADOPTION REVIEW APPROVED; WORKFLOW NOT INSTALLED.
**GitHub approval evidence:** [Owner comment #6685977537](https://github.com/HyungseonSong-plasma/chatgpt-operation/issues/254#issuecomment-6685977537) by authenticated account HyungseonSong-plasma, repository administrator.

The owner's comment explicitly approves **preparation of a scoped, reviewable adoption**, NOT blanket workflow-write permission, bypass, workflow merge, deployment or candidate competition.

## Current implementation handoff

Human-reviewable exact proposed YAML lives at:

- docs/dea-v02-protected-producer-smoke.proposed.yml
- tests/test_dea_producer_smoke_blueprint.py

The YAML is **deliberately not under** .github/workflows/, so it does
not get recognized/activated as GitHub Actions by this draft PR.
It pins all three Actions to exact reviewed upstream Git commit SHAs:

- actions/checkout v7.0.1: 3d3c42e5aac5ba805825da76410c181273ba90b1
- actions/attest v4: 1e69f48acb82d1966a394da916b4c1698aa569d6
- actions/upload-artifact v7.0.2: cf430e030ddbb5b0abf93d22962f4752f3646cd9

The YAML is **only** a noncandidate smoke test: it constructs a
deterministic signed subject with empty observation records and
not-measured metrics. A successful signature confirms cryptographic
toolchain integration only, NOT codeQA evaluation.

## Actual next steps — performed by a human in GitHub

1. **Adopt code separately.** Complete review of code-only Draft PR #249
   and explicitly approve/merge its unprivileged src/tests/docs changes
   through the repository's normal protected-PR process. Do not silently
   mark Draft as merged or create a new Workflow while this code is missing
   from main. CodeQA PR #289 remains a separate dependent decision.
2. **Confirm competent policy authority.** The current Samuel
   repository-mutation-policy.json deliberately denies automation writes
   to .github/workflows/** and to policy/registry. A reviewer must
   acknowledge that the human-run privileged GitHub UI/PR adoption
   is an authorized governance mechanism for this exact path and that
   AI/connector/repository-native mutation providers remain denied.
   If that authority is unavailable, STOP here and request formal
   authorization; do not simulate an approval by Issue comment.
3. **Create a separate human-controlled branch** in GitHub UI, based on
   current protected main; for example issue-254-producer-adoption.
   Open docs/dea-v02-protected-producer-smoke.proposed.yml from reviewed
   source, copy its YAML as the entire contents of
   .github/workflows/dea-evidence-producer.yml. Do not use the AI
   connector to write restricted .github/workflows/**.
4. **Open a dedicated protected PR** that changes exactly the approved
   Workflow file. Reference Issue #254 and its approval comment.
   Review the pinned action SHAs, Environment, permissions and absence
   of push/pull_request_target triggers. Required CI test must pass on
   exact PR HEAD. Ask a separate person for independent security review
   if available; current Ruleset does NOT require one, so record this
   evidence gap honestly.
5. **Human merges only after actual review.** GitHub rules and repository
   policy must be satisfied. The AI/DEA Controller cannot merge.
6. **Perform one bounded smoke dispatch as the human account**:
   Actions -> DEA Human-Approved Signed Artifact Smoke ->
   Run workflow -> ref main; expected_main_sha must be the *current*
   immutable main SHA. Any unrelated main update requires refreshing
   the human input; a stale value must stop the job before signing.
7. **Confirm protective gate:** the signed-smoke job waits for
   dea-human-break-glass approval. A named human personally verifies the
   exact job/commit and chooses Review deployments -> Approve and
   deploy. Without approval, the signing step must not execute.
   Do not paste any personal token or human credential into chat.
8. **Independent readback**: collect the exact Run ID, Job ID, main SHA,
   upload Artifact ID/name/outer digest, subject ZIP SHA-256 and attestation
   ID. Download the uploaded Artifact from the same run; unpack the outer
   wrapper to obtain the exact inner dea-evidence.zip subject. Do not
   execute ZIP contents.

   Example using the human's already authenticated local GitHub CLI:

       gh api --method GET repos/HyungseonSong-plasma/chatgpt-operation/actions/runs/RUN_ID/artifacts
       gh run download RUN_ID --repo HyungseonSong-plasma/chatgpt-operation --name dea-smoke-RUN_ID-1 --dir dea-smoke
       sha256sum dea-smoke/dea-evidence.zip
       gh attestation verify dea-smoke/dea-evidence.zip \
         --repo HyungseonSong-plasma/chatgpt-operation \
         --signer-workflow HyungseonSong-plasma/chatgpt-operation/.github/workflows/dea-evidence-producer.yml \
         --signer-digest EXACT_MAIN_SHA \
         --source-digest EXACT_MAIN_SHA \
         --deny-self-hosted-runners --format json

   Use the actual attempt number in the Artifact name; do not invent
   IDs/digests. Compare signed inner digest to the summary and manifest.
   Compare outer digest with independent GitHub Artifact metadata. Treat
   missing, mismatched, unsigned or unsafe archives as
   HUMAN_REVIEW_REQUIRED.

9. **Record evidence, NOT a Fitness PASS.** Even a genuine GitHub
   Sigstore signature does not independently establish that a particular
   job computed trustworthy science/metrics; the workflow signs a known
   synthetic smoke subject only. Do not admit DEA A/B/C candidates,
   select Champion, or merge further PRs on this result alone.

## Current boundaries

- Repo owner approval comment: VERIFIED.
- Environment setup: OWNER_CONFIRMED; current connector cannot read detail.
- Protect main Ruleset: VERIFIED previously, active with PR and CI test.
- Trusted SHA-pinned smoke YAML: PREPARED, NOT DEPLOYED.
- Workflow policy exception: NOT GRANTED TO AI OR CONTROLLER.
- code-only PR #249: DRAFT OPEN, code not adopted in main.
- Actual GitHub signed Artifact and deployment review: NOT YET EXECUTED.

## Relevant contracts

- docs/dea-v02-producer-attestation-adoption.md
- docs/dea-v02-human-exclusive-emergency-authority.md
- docs/dea-v02-verification-report-2026-11-06.md
