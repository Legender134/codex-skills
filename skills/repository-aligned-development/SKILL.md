---
name: repository-aligned-development
description: Use when changing, testing, reviewing, completing, or preparing submission for work in an existing repository whose local instructions, conventions, worktree state, or branch baseline must govern the task.
---

# Repository-Aligned Development

## Core rule

Explore locally as needed; make each remote or integration submission the smallest coherent task-complete change.

Treat discovery as read-only and every pre-existing change as user-owned.

## Before mutation

For a mutation, inspect status, applicable instructions, configuration, and analogous code. Record the starting commit (or unborn repository state) plus relevant staged, unstaged, and untracked work separately; a HEAD-to-worktree diff can hide staged changes canceled by unstaged edits. For low-risk work, state `Outcome | Baseline | Exploration boundaries | Verification`.

When the user names a remote repository or version as authoritative, record that source, ref, and resolved commit and inspect its original files. Do not infer the current version from webpage summaries or assume a local checkout matches it. Keep the source baseline distinct from installed copies and local user changes; obtain missing source evidence before replacing their contents.

Read [references/repository-contract.md](references/repository-contract.md) when work affects a dependency, public interface, generated-artifact policy, governed subsystem, or materially overlaps user work, and for formal change or branch review. Exploration boundaries protect user work, repository isolation, and authorization; they are not an exact development file allowlist.

## During development

- Reuse repository mechanisms, boundaries, naming, and test style.
- Explore prototypes, alternatives, diagnostics, tests, notes, and temporary artifacts when useful. Authorized local WIP commits may contain exploration; they are not approval to publish it.
- Keep exploratory work identifiable and reversible. The worktree is not automatically the submission candidate.
- Recheck instructions when crossing a repository, safety, dependency, public-interface, or user-work boundary. Continue within existing authorization; ask for direction only when necessary information or authorization is missing, or a new material risk changes the approved scope. More local files or a large intermediate diff alone are not reasons to stop exploring.
- Run repository-native checks in proportion to risk and treat metrics as anomaly signals, never quotas.
- Before any local commit, identify its intended content (which may include authorized WIP), inspect staged and unstaged diffs separately, and verify the exact content the commit will record. Existing index entries are not automatically part of the candidate. Preserve unrelated index entries and worktree versions; use isolated staging or a separate worktree when needed rather than overwriting or consuming user-staged work.

## At delivery

Before reporting a local change, requested commit, or artifact as complete, or publishing or handing it off for integration, read [references/submission-checklist.md](references/submission-checklist.md) and apply the relevant checks below. Publication includes pushing, opening or updating a PR/MR, and requesting remote review. Intermediate authorized WIP commits need the commit-content check above, not final-delivery verification.

1. Identify the candidate and task baseline, plus the integration base, destination remote/branch, and PR/MR target base when applicable. For local-only delivery, mark remote checks inapplicable.
2. Inspect status, name-status, stat, and full diffs from the task baseline, including staged and unstaged changes separately. For every integration delivery, inspect the actual candidate against the integration base, including any earlier commits it carries; the task baseline alone is insufficient. When publishing to a remote, also verify its state and every outgoing commit, plus the actual PR/MR diff when applicable.
3. Select the smallest coherent task-complete diff. Exclude material not needed for the requested outcome or repository requirements, including abandoned alternatives and unrelated exploration. Generated outputs, refactors, and reusable components belong in the candidate when required to complete the task.
4. Preserve unselected work. If unrelated outgoing commits exist, prepare an isolated candidate without rewriting user history; do not publish them merely because they share the branch.
5. Validate the selected candidate in its final location and state. After migration or regrouping, rerun relevant checks there; results from the original worktree do not establish that the candidate is self-contained.

Tests establish behavior only. Passing tests or staying within one directory never proves that every changed file belongs in the submission.

## Local closeout

After a mutating task is delivered, use the local-closeout section of [references/submission-checklist.md](references/submission-checklist.md) to inventory and classify task-relevant local-only state. This is a read-only review, not cleanup; preserve every item until the user authorizes an exact destructive or state-changing action.

## Authorization gates

Reuse existing authorization for the same action and targets. Ask only when necessary information or authorization is missing, or scope or material risk changes.

- **Read-only evidence:** local inspection and remote-ref queries may proceed when needed for the task; prefer queries such as `git ls-remote` when only remote identity is needed.
- **Local state:** task-required edits and reversible preparation may proceed within existing authorization while preserving user work. Fetch updates local objects/refs; use it when missing history is needed for an authorized comparison. Pull, branch switching, and stash change the working context; do not use them merely to simplify discovery.
- **History, cleanup, and publication:** verify that existing authorization covers the operation and targets before reset, clean, material deletion/overwrite/move, history rewrite, commit, push, PR/MR creation or updates, or other external mutation. Authorization to edit alone does not authorize publication or cleanup.

## Stop signals

- No recorded baseline for distinguishing pre-existing user work.
- Exploration crosses a repository, safety, authorization, dependency, or public-interface boundary without review.
- The worktree and the submission candidate are treated as the same set.
- Exploratory or unrelated files are automatically staged because they were produced during the task.
- Directory isolation or passing tests is being used as proof that every changed file belongs in the submission.

## Maintaining this skill

When changing these decision rules, use [tests/behavior/scenarios.md](tests/behavior/scenarios.md) for behavioral evaluation. It is maintenance material, not a checklist for ordinary repository tasks.
