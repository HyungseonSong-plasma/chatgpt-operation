# External LLM review — Gemini pilot (unregistered)

Owner: Samuel reusable read-only review transport. Status: DRAFT / NOT_REGISTERED.
Intended trigger: EXTERNAL_LLM_REVIEW. No GitHub token is supplied.

## Authority and security boundary

ChatGPT/Samuel supplies an independently source-attested, exact SHA Git diff and
review criteria. Gemini receives only this packet, not GitHub credentials or a
repository checkout. The adapter validates the input shape, diff SHA-256 and
output witnesses but does NOT itself establish that the diff came from the
claimed source commit. Untrusted diff contents are data, not tool instructions.

A returned PASS is an independent-review candidate only. It never permits
repository mutation, PR merge, policy adoption, scientific acceptance or
semantic-compatibility certification. Missing/invalid/partial model evidence
must yield UNKNOWN, not a false pass.

## Packet v1

A JSON object with exactly these fields:

- schema_version: integer 1
- repository: owner/name
- base_sha and head_sha: exact 40-hex commit IDs
- diff: unified Git diff, maximum 192000 UTF-8 bytes
- diff_sha256: SHA-256 of exactly the diff's UTF-8 bytes
- changed_paths: 1–50 paths with matching diff headers
- criteria: 1–12 explicit review questions

Output verdict: PASS, REQUEST_CHANGES or UNKNOWN.
Each finding: severity, path, line, verbatim diff evidence, explanation.
Verbatim quoting and path checks are not independent semantic proof; source
line positions and review judgments still require verification.

## API backend (preferred)

Uses Python standard library HTTPS, Google's fixed generateContent endpoint,
explicit model validation and JSON response mode. No model tools are requested.
Uses GEMINI_API_KEY from a trusted environment secret; never commit this key.

Example (from an exact Samuel checkout):

    PYTHONPATH=src python3 -m chatgpt_operation.controller.gemini_review_adapter \
      --input /isolated/request.json --output /isolated/result.json \
      --backend api --model gemini-2.5-flash

Default timeout 90 sec (maximum 180), max generation 2048 tokens.
Provider quota, prices and success are not asserted by this draft.

## CLI backend (optional; requires external sandbox)

Uses Gemini CLI headless --prompt and --output-format json, with Plan approval
mode, stdin packet, temporary empty current directory and limited environment.
No GitHub credentials are forwarded. These measures do NOT prove a security
boundary against a compromised CLI or headless plan-mode transitions.

SAMUEL_GEMINI_CLI_SANDBOX=1 is an OPERATOR ASSERTION ONLY; it is not a
verifiable attestation and must not be set without independent host-level
filesystem/credential/network confinement. Do not mount the source repository
in the CLI execution sandbox.

## ChatGPT-accessible ingress proposal (not installed)

The linked ChatGPT GitHub connector can create an Issue, add a label, observe
Actions runs and retrieve result artifacts; it currently exposes no direct
workflow_dispatch operation. The proposed route therefore uses **one
owner-created Issue plus one owner-applied label**. The host is
HyungseonSong-plasma/chatgpt-operation; v0.1 allows only public codeQA PRs.

The entire Issue body must be JSON with schema:

    {
      "schema_version": 1,
      "request_type": "SAMUEL_GEMINI_REVIEW",
      "pr_number": 300,
      "packet": {
        "schema_version": 1,
        "repository": "HyungseonSong-plasma/codeQA",
        "base_sha": "<40 lowercase hex>",
        "head_sha": "<40 lowercase hex>",
        "diff": "<exact raw GitHub PR diff>",
        "diff_sha256": "<64 lowercase hex of UTF-8 diff>",
        "changed_paths": ["docs/README.md"],
        "criteria": ["Review ..."]
      }
    }

The Issue title must start with [Gemini Review]. Apply the
samuel/gemini-review-approved label **once**, only after confirming the packet.
The body and resulting Issue are public: do not include credentials, private
code or privileged review data. The checked-in proposed workflow is
automation/gemini-review/samuel-gemini-review.proposed.yml; it is not an
executable GitHub Actions workflow until separately installed.

The ingress verifier requires owner sender and issue creator, an open issue,
the exact approved label, a single owner label event, an allowlisted repo, an
open PR targeting main, matching current head/base Git SHAs, the exact
unified GitHub diff bytes and the complete current changed-file inventory.
A new PR push or nonidentical diff blocks the request.

The workflow proposal splits preparation (GitHub read token, no Gemini key)
from execution (Gemini key, no GitHub token, trusted Samuel checkout only).
The model receipt must bind the prepared request digest and exact PR identity.
Neither the model nor an artifact is a GitHub review approval. ChatGPT should
use the result artifact only to report findings and ask a separate merge
decision. UNKNOWN is an operational verdict, not a request to retry payment.

A request is bounded by 52 KB of public issue-body data, at most 50 files,
one initial owner label event, GitHub run_attempt 1, 90-second timeout,
2048 generated tokens and seven-day artifact retention. **This is not a
financial spending ceiling**; set the Google project's rate/quota/billing
controls before activation. Gemini CLI stays disabled in hosted Actions;
it requires separate executable sandbox attestation.

## Exact privileged activation plan

automation/gemini-review/activation-proposal-v0.1.json records the desired
EXTERNAL_LLM_REVIEW provider. Activation additionally requires creating the
approval label, provisioning SAMUEL_GEMINI_API_KEY in GitHub Actions Secrets
without publishing its value, installing and pinning the workflow under
.github/workflows/, and registering the provider in
skills/capability-registry.json **through the authorized protected-file
governance path**. The normal mutation policy denies both destinations;
this PR does not modify either and cannot activate the route.

The new reusable skill can later be adopted by codeQA through a separate exact
central revision pin update. Running a one-off external review of a public
codeQA PR through Samuel's own Issue queue does not, by itself, upgrade codeQA
or change its domain acceptance policy.

## Activation / unresolved gates

1. Draft PR: validate mock API/CLI transports and adversarial failures in CI.
2. Privileged review of changes to skills/capability-registry.json (normal
   Samuel mutation policy explicitly forbids modifying it).
3. Privileged review of a .github/workflows execution/receipt path (also denied
   by normal policy), including secure secrets, cost/quota/timeout caps,
   exact-SHA input and provider receipt verification.
4. Explicit consumer pin adoption (codeQA does not auto-upgrade).
5. Live Gemini smoke evidence, independent domain review, and separate merge
   authorization.

The central Skill Catalog indexes EXTERNAL_LLM_REVIEW as a trigger-only
metadata entry, but no executable provider is registered in the privileged
Capability Registry and no Controller/Actions execution route is installed.
Until those separate gates pass, codeQA-init does not activate this skill and
ChatGPT cannot dispatch Gemini reviews through a live Samuel capability.
