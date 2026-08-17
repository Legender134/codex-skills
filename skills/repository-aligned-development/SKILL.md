---
name: repository-aligned-development
description: Use when changing, testing, reviewing, completing, or preparing submission for work in an existing repository whose local instructions, conventions, worktree state, or branch baseline must govern the task.
---

# Repository-Aligned Development

## Core rule

Understand the repository before designing; implement in its own style; control scope throughout; use submission time for verification, not large-scale rework.

Treat discovery as read-only and every pre-existing change as user-owned.

## Choose workflow depth

For a read-only answer, inspect only enough context to answer reliably. Do not create a contract or use the submission checklist unless reviewing a change or branch.

Use a **micro-contract** only when all are true:

- the mutation is local and low-risk with a clear baseline;
- applicable repository rules and nearby patterns are unambiguous;
- no dependency, public interface, generated-artifact policy, or subsystem changes;
- no material overlap with user-owned work;
- the task is not change/branch review, a formal handoff/completion audit, or submission preparation.

Inspect relevant status, instructions, configuration, and analogous code, then state `Outcome | Scope and non-goals | Verification` before editing.

Otherwise use the **full contract**. Read [references/repository-contract.md](references/repository-contract.md) before design, implementation, review findings, completion, or submission; complete its discovery and state the task-local contract before proceeding. Escalate a micro-contract to the full contract as soon as any condition above stops being true.

## Align and verify

1. Reuse established mechanisms, boundaries, naming, and test style.
2. Make the smallest task-complete diff. Avoid unrelated refactors, broad formatting, generic docs/tests, test-only production interfaces, and abandoned implementations.
3. Keep experiments outside the formal diff from the start; migrate only the selected result.
4. Recheck the contract when scope, dependencies, subsystems, or patterns change. Pause for user direction before a heavyweight dependency or public interface.
5. Run repository-native checks in proportion to risk. Inspect the full affected diff plus relevant untracked, large, and generated files; explain deviations and validation gaps. Treat metrics as anomaly signals, never quotas.
6. For change/branch review, a formal handoff/completion audit, or submission, read [references/submission-checklist.md](references/submission-checklist.md) and report fresh evidence.

## Authorization gates

Perform fetch, pull, branch switching, reset, clean, stash, material deletion/overwrite/move, history rewrite, commit, push, merge-request/pull-request creation, or any external mutation only when task scope requires it and the user has authorized it. Preserve experiments or propose selective migration when cleanup is not authorized.

## Rationalization counters

| Rationalization | Counter |
|---|---|
| This is small, so no contract is needed. | State the micro-contract or use the full contract. |
| “大量的测试、文档” proves completeness. | Repository evidence decides what belongs. |
| “收敛是不是要直接开始删除文件了” | Metrics do not authorize deletion or history cleanup. |
| “upload now, clean up later” | Verify the scoped formal diff before any authorized publication. |

## Red flags — stop

- No micro- or full contract before a repository mutation.
- Experiments are accumulating in the formal diff or separation is deferred until submission.
- “大量的测试、文档” is treated as proof of completeness.
- “收敛是不是要直接开始删除文件了” or “upload now, clean up later” is driving action.
