---
name: planned-development
description: Explicitly requested design and implementation planning for a substantial change, followed by scoped execution and review. Invoke by name when a written design or multi-step plan is wanted; ordinary fixes and explanations use the normal workflow.
---

# Planned Development

Use this workflow when the user explicitly asks for it or names this skill. Scale the design and plan to the requested change. User authorization continues across turns; presenting a plan does not create an additional approval gate for work already authorized.

## Resolve the decision

Inspect applicable instructions, the worktree baseline, nearby implementation, and relevant tests. Identify the requested behavior, important constraints, and the decisions that remain open. Ask only questions whose answers materially affect the result. Where alternatives matter, compare their concrete tradeoffs and recommend one; do not generate alternatives merely to satisfy a count.

Keep the design in the conversation unless a repository document is requested or needed by its existing process. A clear bounded change may need only a few sentences. Do not create a spec, branch, worktree, dependency, or commit solely because this skill was invoked.

## Plan and execute

For work that benefits from a plan, record ordered steps, affected boundaries, acceptance checks, and unresolved decisions. Prefer the repository's existing format. Keep temporary plans outside the submission unless they are a requested deliverable.

Proceed with authorized reversible implementation and verification. Pause only for missing necessary information, a new material risk, or an action outside existing authorization. Preserve unrelated user changes and unselected exploratory work. Use repository-native tests proportionate to behavior and risk; meaningful regression tests are useful for a bug, while a configuration-only edit may need native parsing and runtime checks.

## Optional delegation

Keep small tasks with the primary. Delegate a bounded independent subtask only when it usefully overlaps other work and the live tool contract allows it. Use current configured roles, respect the active child limit, and keep one writer per worktree, including the primary. Pass only the goal, paths, evidence, constraints, and acceptance criteria needed by that worker. Do not hard-code model names or require every role to run as a pipeline.

## Review and finish

Compare the result with the requested behavior and the actual task diff. Check edge cases and repository-native validation relevant to the change. Use independent review for concrete complexity or risk, rather than dispatching a reviewer for every edit. Re-diagnose repeated failures from evidence; do not mechanically add retry rounds or increase reasoning effort.

Report what changed, verification results, and material limitations. Remote publication follows the user's existing authorization and exact submission scope. Preserve local plans, artifacts, and worktrees until any cleanup has explicit target-level authorization; completion does not imply permission to delete them.
