# RFC-0001 — Portable ChatGPT Operation Skills

**Status:** REVIEW  
**Scope:** central reusable skill architecture  
**Initial consumer:** `HyungseonSong-plasma/moose-test-repo`

## 1. Motivation

Operational rules currently live partly in natural-language instructions and partly in repository-local automation.

The working hypothesis is:

> LLMs should own semantic intent and judgment. Repetitive, deterministic, machine-verifiable operating procedures should be implemented as reusable skills.

The first validated example is the repository-mutation capability in `moose-test-repo`, which mechanizes fresh-read, exact identity, no-op, CI-lock, mutation, and read-back checks.

The next step is to make that capability portable across repositories without copying code or duplicating rules.

## 2. Proposed ownership model

`chatgpt-operation` becomes the central source for reusable operating capabilities.

```text
chatgpt-operation
├── Python package / CLI
├── reusable GitHub workflows
├── schemas
├── shared tests
└── skill documentation
             │
             ├──────── exact-SHA consumer pin ────────┐
             ▼                                        ▼
       moose-test-repo                           other repos
       local policy                              local policy
       local manifests                           local manifests
```

The central repository owns **how a generic operation is safely executed**.

Each consumer repository owns **what that repository permits**.

## 3. Proposed package layout

```text
chatgpt-operation/
├── pyproject.toml
├── src/
│   └── chatgpt_operation/
│       ├── cli.py
│       ├── repository/
│       │   └── mutation.py
│       ├── git/
│       └── validation/
├── schemas/
│   ├── repository-mutation.schema.json
│   └── repository-policy.schema.json
├── skills/
│   └── repository-mutation/
│       └── README.md
├── .github/
│   └── workflows/
│       └── repository-mutation.yml
└── tests/
```

The Python package is the deterministic engine.

The reusable workflow is the GitHub-hosted execution surface.

The Markdown skill documentation describes intent, boundaries, and review guidance; it is not the enforcement mechanism.

## 4. Consumer layout

A consumer should remain thin.

```text
consumer-repo/
├── .chatgpt-operation.yml
├── automation/
│   └── mutations/
│       └── *.json
└── .github/
    └── workflows/
        └── repository-mutation.yml
```

The caller workflow should reference the central workflow by an **exact commit SHA**, not by a moving branch.

Example concept:

```yaml
jobs:
  mutate:
    uses: HyungseonSong-plasma/chatgpt-operation/.github/workflows/repository-mutation.yml@<exact-sha>
    with:
      manifest: automation/mutations/update.json
```

## 5. Package distribution

The core should also be usable outside GitHub Actions.

Proposed CLI:

```bash
chatgpt-op repository mutate --manifest mutation.json
```

Proposed Python API:

```python
from chatgpt_operation.repository.mutation import MutationEngine
```

Initial distribution options:

1. install directly from the private Git repository at an exact commit;
2. build wheel artifacts on tagged releases;
3. add a private Python registry or PyPI publication only if operationally justified later.

Copying `mutation.py` independently into every consumer repository is explicitly rejected because it creates skill drift.

## 6. Repository policy boundary

The generic engine must not embed `moose-test-repo` assumptions.

Consumer policy should be declarative, for example:

```yaml
schema_version: 1

repository:
  protected_branches:
    - main

mutation:
  allow:
    file: [create, update, delete]
    branch: [create, move, delete]
    issue: [update, close, reopen]

lock:
  workflows:
    - Repository CI
    - Governed refactor entrypoint
```

The central engine validates the policy schema and fails closed for unsupported fields or actions.

Policy should be treated as authorization constraints, not suggestions.

## 7. Repository-mutation generic contract

The portable engine should preserve the validated mechanical sequence:

```text
declared semantic intent
    ↓
repository / resource / action binding
    ↓
consumer policy authorization
    ↓
mutation-lock evaluation
    ↓
fresh canonical read
    ↓
exact expected identity gate
    ↓
semantic no-op gate
    ↓
mutation
    ↓
read-back verification
    ↓
PASS | NO_MUTATION_NEEDED | HARD_STOP
```

Initial generic resource support:

| Resource | Actions | Identity |
|---|---|---|
| file | create/update/delete | absence or blob SHA |
| branch | create/move/delete | absence or exact head SHA |
| issue | update/close/reopen | exact updated-at identity |

Branch movement remains fast-forward only by default.

History rewrite is not part of v1.

## 8. Lock policy

The current prototype blocks when any other queued/in-progress Actions run exists.

That is intentionally conservative but may be too repository-specific.

Portable v1 should support a policy-defined lock set.

Candidate semantics:

```text
lock.mode = named_workflows | all_actions
lock.workflows = [...]
lock.ignore_current_run = true
```

Open question: should the default be `all_actions` (safer) or require each consumer to declare a lock policy explicitly (less surprising)?

## 9. GitHub authentication and permissions

The reusable workflow should run using the **consumer repository's workflow token**, not a long-lived token stored in `chatgpt-operation`.

Principles:

- least privilege;
- no token in manifests;
- no token in artifacts/logs;
- explicit permissions in the caller/reusable workflow contract;
- read-only review workflows must not acquire mutation permission;
- mutation workflow should expose only closed-world resource/action paths.

Open question: which permission split best avoids over-granting for a workflow supporting files, refs, and issues in one entrypoint?

Possible answer:

```text
contents: write
issues: write
actions: read
```

but reviewers should challenge whether separate workflows per resource class are safer.

## 10. Supply-chain and versioning model

Consumer repositories should pin reusable workflows and Python package sources to immutable revisions.

Proposed lifecycle:

```text
central change
→ central tests/review
→ tagged release / immutable commit
→ consumer pin-update PR
→ consumer CI
→ adoption
```

Candidate semantic versioning:

- PATCH: implementation fix with unchanged manifest/policy contract;
- MINOR: backward-compatible resource/action/schema extension;
- MAJOR: schema or authorization semantics change.

Open question: should exact commit SHA remain canonical even when release tags are published?

Proposed answer: yes. Tags are human-readable discovery aliases; consumer execution pins exact SHA.

## 11. Reusable workflow boundary

The reusable workflow should be thin.

It should:

1. check out the central implementation at the referenced immutable revision;
2. check out/read the consumer manifest and policy;
3. establish execution identity;
4. invoke the package;
5. emit structured result artifacts.

It should not duplicate mutation logic already implemented in the package.

## 12. Review and test strategy

Central tests should include:

- manifest schema negative controls;
- policy schema negative controls;
- stale file identity;
- stale branch identity;
- stale issue identity;
- no-op suppression;
- non-fast-forward rejection;
- lock-policy enforcement;
- wrong repository binding;
- post-write verification mismatch;
- token/secret redaction;
- consumer-policy denial;
- package/CLI equivalence.

A local fake/in-memory transport remains mandatory for mutation self-tests.

No test may create live GitHub resources merely to prove connectivity.

Integration testing against GitHub should use explicitly provisioned test fixtures or ephemeral repositories, never production repositories.

## 13. Migration plan for moose-test-repo

```text
Phase 1
  bootstrap central package + schemas + tests

Phase 2
  port current repository-mutation implementation
  preserve behavior

Phase 3
  add reusable workflow
  add repository-policy adapter

Phase 4
  consume central skill from moose-test-repo at exact SHA
  run full consumer CI

Phase 5
  remove vendored skills/repository/mutation.py
  retain only local policy + manifests + thin caller
```

Portability is not considered proven until Phase 4 passes in a real consumer repository.

## 14. Deliberate non-goals for v1

- scientific reasoning;
- deciding whether a requested semantic change is desirable;
- force push/history rewriting;
- release/package/project mutations;
- arbitrary GitHub API passthrough;
- executing commands supplied by a mutation manifest;
- automatically expanding authorization beyond consumer policy.

## 15. Architecture principles to preserve

1. **LLM intent, deterministic execution.**
2. **Fail closed on unknown schema/action.**
3. **Exact identity before destructive mutation.**
4. **No semantic no-op history.**
5. **Read-back after mutation.**
6. **Consumer repository owns authorization policy.**
7. **Central package owns generic mechanics.**
8. **Consumers pin immutable central revisions.**
9. **No duplicated skill implementation across repositories.**
10. **Reviewability before automation convenience.**

## 16. Reviewer questions

Reviewers should explicitly challenge:

1. Is the package + reusable-workflow split appropriate, or should only one distribution mechanism exist?
2. Is a private central repository compatible with reliable reusable-workflow consumption across the owner's private repositories?
3. Does exact-SHA pinning sufficiently address central supply-chain risk?
4. Is the proposed consumer policy expressive enough without becoming another large rule language?
5. Should CI locks be centralized mechanics or entirely consumer-defined policy?
6. Is a single mutation workflow with `contents: write` + `issues: write` too broad?
7. Should file/ref/issue mutation engines be separate packages/workflows for permission isolation?
8. Is `updated_at` a sufficiently strong issue concurrency identity, or should v1 use another conflict-control mechanism?
9. What is missing for package integrity, provenance, release signing, and reproducibility?
10. Which parts of the current repository-mutation prototype should **not** be generalized?

## 17. Acceptance for this RFC

This RFC should not be accepted until:

- at least two independent automated reviewers have examined it where available;
- security/permission objections are dispositioned;
- the package/reusable-workflow boundary is explicit;
- consumer policy ownership is explicit;
- migration can be performed without weakening the current `moose-test-repo` mutation safety contract.
