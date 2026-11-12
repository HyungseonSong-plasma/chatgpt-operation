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
