---
name: repository-aligned-development
description: Use when Codex implements, modifies, fixes bugs, refactors, tests, reviews repository changes or branches, or prepares submission in an existing repository where repository-local instructions, preservation of user changes, minimal diffs, and approval before destructive Git or filesystem operations matter.
---

# Repository-Aligned Development

## Core rule

Understand the repository before designing; implement in its own style; control scope throughout; use submission time for verification, not large-scale rework.

Apply evidence in this order:

1. Explicit user instructions for this task.
2. Authoritative repository instructions.
3. Build, dependency, test, format, lint, and CI configuration.
4. Analogous nearby code/tests and recent history.
5. Applicable organization policy.
6. General engineering practice.

Resolve material conflicts with the user. Apply compatible lower-precedence guidance, but never let it silently override stronger evidence.

## Choose the mode

Lightweight read-only explanations, status requests, and focused read-only file/function reviews may inspect only enough context to answer reliably; they need neither a full contract nor the submission checklist. Use the full workflow for any repository change, review of a repository change or branch, completion, or submission. Discovery is read-only by default, and every pre-existing change is user-owned.

## Full workflow

1. **Discover.** Inspect the relevant root/subproject, branch, upstream/base/merge base, tracked/modified/untracked state, scoped instructions, configuration, analogous code/tests, and recent history.
2. **Contract.** For work using this full workflow, read [references/repository-contract.md](references/repository-contract.md) before design, implementation, review findings, completion, or submission. After discovery and conflict resolution, state or confirm an explicit, evidence-backed task-local contract. Never skip this output.
3. **Align work.** Reuse established mechanisms and boundaries. Make the smallest task-complete diff; avoid unrelated refactors, broad formatting, generic docs/tests, test-only production interfaces, and abandoned implementations. Keep experiments outside the formal submission diff in an ignored or isolated workspace from the start; migrate only the selected result. Before a heavyweight dependency or public interface, pause and request user direction. Recheck the contract for lesser dependency, subsystem, unfamiliar-pattern, or scope changes.
4. **Verify drift.** Run repository-native checks in proportion to risk, inspect the complete diff and untracked/large/generated files, then compare results with the contract. Explain deviations and gaps. Metrics are anomaly signals, never quotas.
5. **Prepare submission.** For review of a repository change or branch, completion, or submission, read [references/submission-checklist.md](references/submission-checklist.md) and report fresh evidence and merge conditions.

## Authorization gates

Perform fetch, pull, branch switching, reset, clean, stash, material deletion/overwrite/move, history rewrite, commit, push, merge-request/pull-request creation, or any external mutation only when task scope requires it and the user has authorized it. Preserve experiments or propose selective migration when cleanup is not authorized.

## Rationalization counters

| Rationalization | Counter |
|---|---|
| The conflict is resolved, so the contract is implied. | State the contract explicitly before proceeding. |
| “大量的测试、文档” proves completeness. | Repository evidence decides what belongs. |
| “收敛是不是要直接开始删除文件了” | Metrics do not authorize deletion or history cleanup. |
| “upload now, clean up later” | Verify the scoped formal diff before any authorized publication. |

## Red flags — stop

- No explicit contract after discovery/conflict resolution.
- Experiments are accumulating in the formal diff or separation is deferred until submission.
- “大量的测试、文档” is treated as proof of completeness.
- “收敛是不是要直接开始删除文件了” or “upload now, clean up later” is driving action.
