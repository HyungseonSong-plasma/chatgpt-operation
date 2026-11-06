# DEA v0.1 — codeQA Pipeline evidence-only pilot

**Issue:** [David Evolutionary Arena #246](https://github.com/HyungseonSong-plasma/chatgpt-operation/issues/246)  
**Scope approved in discussion:** source-grounded **read-only** historical replay.  
**No approval:** Arena candidate branches, David promotion, production branch mutations,
new model/API spending, automatic champion selection, policy changes, or merges.

## What is being measured?

Use the already merged codeQA [PR #188](https://github.com/HyungseonSong-plasma/codeQA/pull/188)
as a controlled *historical before/after* observation. This is **not** a set
of independently developed Arena candidates from one base. The narrower
question is whether the evaluation machinery preserves source identity,
identical measurement denominators and evidence uncertainty.

Source pins (not floating branch names):

- Before: `fb54b6c92363476b07a726008fbe8c1ab35f1a6a`
- After: `6aa15e8613b95bf39233a7b191a730f257d7adb3`

Independently inspect **all 12 tracked**
`src/codeqa/pipeline/*.py` paths at both exact commits using local Git
objects. The oracle is a Python AST census of *direct* `subprocess` imports.
It rejects changed file sets, missing/unrelated commits, invalid Python,
and Git object/hash disagreements instead of substituting unknowns for PASS.

Prior GitHub source and blob readbacks show **2 → 0** direct imports.
This observation concerns Git-access responsibility, not universal architecture
quality. The accepted codeQA role policy assigns Git subprocess access to
`infrastructure.git.GitReader`, retaining Pipeline composition.

## Reproduce with a local clone

A complete Git history containing both commits is required; source retrieval
or fetching the repository is **not** performed by the tool.

```bash
PYTHONPATH=src python3 -m unittest tests.test_dea_v01_replay -v
PYTHONPATH=src python3 -m chatgpt_operation.controller.dea_v01_replay \
  --repo /path/to/codeQA \
  --before fb54b6c92363476b07a726008fbe8c1ab35f1a6a \
  --after 6aa15e8613b95bf39233a7b191a730f257d7adb3
```

The result always has `decision=EVIDENCE_ONLY`, `champion=null`,
`champion_promoted=false`, and `repository_mutation_authorized=false`.
Source-level reduction, even if valid, cannot authorize a PR or merge.

## Deliberately unproven

- Historical codeQA B8 [baseline run 40643089804](https://github.com/HyungseonSong-plasma/codeQA/actions/runs/40643089804)
  and [later run 42000776739](https://github.com/HyungseonSong-plasma/codeQA/actions/runs/42000776739)
  reported the same **43/48** static Pipeline cross-role imports. This
  tool does not fetch/rehash their artifact ZIPs; those results remain
  historical separate evidence, not metrics silently folded into fitness.
- The codeQA [43-edge ledger](https://github.com/HyungseonSong-plasma/codeQA/blob/main/docs/architecture-qa-184-close-first-evidence.md)
  records **zero viable B4 automatic package moves** (3 occupied targets,
  2 policy-boundary rejections). Do not invent viable candidates.
- External consumers, API/runtime behavior, semantic ownership completeness,
  and equivalent cross-candidate fitness/acceptance oracles are
  **NOT_EVALUATED**. CI success is not domain acceptance.
- Original DEA v0.1 Pareto/fitness contract still requires real candidate
  branches with common base and equal verified gates to be considered for
  comparative selection; none are created or selected here.

## Forward gate (separate approval required)

Before v0.2: freeze an executable task-specific acceptance oracle,
pin analyzer/profile/CI revision for every candidate, independently validate
hard gates and source/artifact identities, and establish safety, compute
and human-review budgets. Issue #246 continues to govern David promotion.
