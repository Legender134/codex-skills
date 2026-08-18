---
name: repository-aligned-development
description: Use when changing, testing, reviewing, completing, or preparing submission for work in an existing repository whose local instructions, conventions, worktree state, or branch baseline must govern the task.
---

# Repository-Aligned Development

## Core rule

Explore locally as needed; make each remote or integration submission the smallest coherent task-complete change.

Treat discovery as read-only and every pre-existing change as user-owned.

## Before mutation

For a mutation, inspect status, applicable instructions, configuration, and analogous code. Record a baseline that distinguishes pre-existing user work. For low-risk work, state `Outcome | Baseline | Exploration boundaries | Verification`.

Read [references/repository-contract.md](references/repository-contract.md) when work affects a dependency, public interface, generated-artifact policy, governed subsystem, or materially overlaps user work, and for formal change or branch review. Exploration boundaries protect user work, repository isolation, and authorization; they are not an exact development file allowlist.

## During development

- Reuse repository mechanisms, boundaries, naming, and test style.
- Explore prototypes, alternatives, diagnostics, tests, notes, and temporary artifacts when useful. Authorized local WIP commits may contain exploration; they are not approval to publish it.
- Keep exploratory work identifiable and reversible. The worktree is not automatically the submission candidate.
- Recheck instructions and pause for direction when crossing a repository, safety, or authorization boundary; changing a public interface; adding a heavyweight dependency; or materially overlapping user-owned work. More local files or a large intermediate diff alone are not reasons to stop exploring.
- Run repository-native checks in proportion to risk and treat metrics as anomaly signals, never quotas.

## At delivery

Before pushing to a remote, opening or updating a pull/merge request, requesting remote review, or handing work to another person for integration, read [references/submission-checklist.md](references/submission-checklist.md), then:

1. Derive exact candidate paths and deliverables from the requested outcome.
2. Inspect `git status` and the name-status, stat, and full branch diff from the recorded baseline through `HEAD`, including relevant uncommitted changes.
3. Select the smallest coherent task-complete diff. Leave unrelated user work, abandoned alternatives, experiments, generated evidence, broad refactors, generic frameworks, and unnecessary tests or documentation out of the candidate.
4. Preserve unselected local work rather than staging, committing, overwriting, or deleting it without authorization.

Tests establish behavior only. Passing tests or staying within one directory never proves that every changed file belongs in the submission.

## Local closeout

After a mutating task is delivered, use the local-closeout section of [references/submission-checklist.md](references/submission-checklist.md) to inventory and classify task-relevant local-only state. This is a read-only review, not cleanup; preserve every item until the user authorizes an exact destructive or state-changing action.

## Authorization gates

Perform fetch, pull, branch switching, reset, clean, stash, material deletion/overwrite/move, history rewrite, commit, push, merge-request/pull-request creation, or any external mutation only when task scope requires it and the user has authorized it. Preserve experiments or propose selective migration when cleanup is not authorized.

## Stop signals

- No recorded baseline for distinguishing pre-existing user work.
- Exploration crosses a repository, safety, authorization, dependency, or public-interface boundary without review.
- The worktree and the submission candidate are treated as the same set.
- Exploratory or unrelated files are automatically staged because they were produced during the task.
- Directory isolation or passing tests is being used as proof that every changed file belongs in the submission.
