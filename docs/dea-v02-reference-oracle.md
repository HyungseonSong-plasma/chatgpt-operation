# DEA v0.2 — bounded independent documentation-reference Oracle

**Owner-selected task:** codeQA issue #288, phase-2 documentation-reference impact analysis.
**Implementer:** src/chatgpt_operation/controller/dea_reference_oracle.py.
**Status:** read-only observation and adversarial tests; **not** a live candidate competition, full Markdown validator, independent human review, or merge authorization.

## Independent source and semantic evidence

The Oracle does not import or reuse the existing codeQA PR #289 reference-audit implementation. It uses a separately implemented lexical reference scanner, manually curated golden fixtures, negative controls, and read-only, exact Git-object readback.

On a trusted runner, scan_git_snapshot reads an immutable commit using git rev-parse, git ls-tree and git cat-file. It verifies selected Git blob identities and captures the complete tracked-path denominator and selected text-corpus digest. No codeQA code is imported or executed. The selected text formats are Markdown, Python, JSON, YAML, TOML, TXT, shell, INI and CFG; per-file size is bounded at 4 MB.

Each observed reference includes source path and line, reference kind, raw target, resolved target, fragment and status. The supported subset includes simple inline Markdown/image links, reference-style uses/definitions, HTML href/src, GitHub-style heading slug approximation, explicit HTML IDs, and separate literal-path enumeration. Fenced and inline code examples are excluded from Markdown hyperlink counts.

**Uncertainty is explicit:** Unsupported Markdown grammar, uncertain fragment resolution, external URLs, untracked external deep links, and the semantic meaning of a quoted docs-path literal are NOT proven by this scanner. External consumers are always NOT_EVALUATED. The module cannot claim full CommonMark or GitHub UI rendering equivalence.

A candidate's exact revision, corpus digest, file denominator and reference observations must all match the trusted Oracle. Agreement is only PASS_BOUNDED. Differences are FAIL; unsupported syntax triggers UNKNOWN. Neither status grants a champion or repository mutation.

For strategy C, compare_transition independently scans the full selected corpus at both exact versions and checks the declared changed paths. This rejects stale incremental caches and incomplete invalidations; passing does not itself prove incremental runtime savings. A and B must satisfy the same oracle and hard gates.

## Initial real-codeQA preview (not the adopted competition base)

CI fetches pinned PR #289 preview source da14ec9bd6bdbea2b535bd91331b88ecce698413 and independently reads its Git blobs. This validates source-observation mechanics but does not certify all Markdown constructs or approve any document move.

PR #289 is still open. The codeQA competition base in docs/dea-v02-codeqa-document-reference-pilot.json is intentionally null until phase-1's review/merge is complete and the adopted exact SHA is refreshed.

## Remaining admission conditions

1. Confirm complete required Markdown/consumer scope, golden expected observations and explicit UNKNOWN policy.
2. Implement a trusted exact-HEAD candidate-output runner with independent artifact/CI receipt verification. Caller-supplied result JSON is not independently authenticated.
3. Freeze the accepted codeQA source SHA, same-runner workloads, benchmarks, repeat counts and equal model/compute budgets for A/B/C.
4. Complete independent review/owner authority before any merge or David promotion. Gemini-based external review has been postponed, not waived.

All work so far is evidence-only; candidate branch creation and any policy changes remain blocked until the admission gates are met.
