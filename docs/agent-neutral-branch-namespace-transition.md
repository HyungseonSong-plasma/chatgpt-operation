# Agent-neutral branch namespace transition

## Decision and scope

For newly initiated automated work use `agent/<issue-or-work-id>-<short-purpose>` instead of embedding a model or agent name in the branch prefix. The controller/issue/PR metadata owns the acting agent identity; a future Samuel-to-David transition must not require renaming Git branches.

The canonical repository-side mutation policy is
[`automation/samuel/repository-mutation-policy.json`](../automation/samuel/repository-mutation-policy.json).
This proposal **adds** `agent/*` to its branch allowlist without altering file-path rules, default-branch restrictions, capability routing, blocker history or credentials.

## Phases

| Phase | New work | Existing work | Enforcement |
| --- | --- | --- | --- |
| 0: Before this PR merges | Existing policy applies (`samuel/*`, `issue-*`) | Keep current refs unchanged | No claim that `agent/*` is authorized yet |
| 1: After approved policy PR merges | Prefer `agent/*`; continue `issue-*` where appropriate | `samuel/*` remains allowed | Samuel repository-native source policy + applicable caller-side checks |
| 2: After independent GitHub Ruleset activation | `agent/*`, `issue-*` | `samuel/*` temporarily exempted | GitHub server-side branch rule, subject to actual test receipts |
| 3: After legacy PRs and active jobs finish | `agent/*`, `issue-*` | Remove `samuel/*` exemption only after owner approval and no live references | Coordinate a separate reviewed policy and Ruleset revision |

The transitional allowlist **does not itself prevent new `samuel/*` branches**. That requires controller behavior change and a later scoped creation-only restriction, if the owner wants hard enforcement. Do not claim legacy names have already been retired.

Existing refs, including [documentation QA #252](https://github.com/HyungseonSong-plasma/chatgpt-operation/pull/252) and independent DEA #249, must remain unmodified by this policy migration. Existing `feat/*` refs are not automatically deleted.

## GitHub Ruleset administrator handoff

The GitHub Connector currently exposes read-only Ruleset inspection, not creation or modification. A repository administrator must configure the server-side rule independently. The repository's current Ruleset inventory must be re-read before creation; do not create a duplicate.

Suggested Ruleset (review precise pattern semantics and unrelated automation before enabling):

- Name: `Agent-neutral branch naming`; target: branch; status: Active only after a safe dry-run of pattern selection where available.
- Include: all branches.
- Exclude the permitted families: `main`, `agent/*`, `agent/**/*`, `issue-*`, `samuel/*`, `samuel/**/*`. The two `**/*` exclusions cover nested agent/Samuel branch names if GitHub's matching semantics require it.
- For matched (non-exempt) branches: restrict creations; optionally restrict updates **after** checking effects on existing nonconforming branches. Do not use this Ruleset to weaken the separate default-branch protections.
- Keep the bypass list empty unless a distinct repository-owner exception is explicitly approved. GitHub availability and the precise UI controls depend on repository plan and current product behavior.
- GitHub's target-pattern language and Python's `fnmatch.fnmatchcase` do **not** necessarily match all nested or exotic strings identically. Validate actual accepted/rejected names, and do not assume the two controls are equivalent based only on matching pattern text.
- If the Ruleset cannot express this policy on the current plan, leave server-level enforcement `NOT_IMPLEMENTED`; retain caller-side validation and document the gap rather than claiming all direct GitHub calls are protected.

Validation matrix after Ruleset activation:

| Branch target | Expected |
| --- | --- |
| `agent/251-doc-qa` | Allowed |
| `agent/team/subtask` | Allowed if nested paths are intended and tested |
| `issue-251-doc-qa` | Allowed |
| `samuel/document-status-qa-251` | Allowed during migration |
| `feat/new-task` | Rejected |
| `david/new-task` | Rejected |
| `main` | Governed by **separate** default branch rules |

A successful GitHub Actions unit test is not proof of server-side Ruleset activation. Record the Ruleset ID, enforcement status, selected include/exclude patterns, bypass list and safe test receipts before reporting connector-wide enforcement.

## Non-goals

No protected-branch merge, no direct edit to `main`, no previous denial clearance, no consumer pin update, no DEA PR changes, and no claim that a branch prefix proves agent identity, semantic compatibility or review.
