# Windows global routing instructions

The Windows environment is responsible for GUI work, browser work, manual point-cloud selection and inspection, Windows applications, PowerShell, mirror checks, and other miscellaneous local operations. Keep Windows and WSL duties independent.

Do not delegate trivial questions, explanations, single-file changes, single-command checks, or work whose scope is not yet clear. The active child-agent concurrency cap on Windows is **1**. Never run overlapping writers or allow two roles to modify the same files or repository state.

Delegated work must return distilled evidence: the question answered, relevant paths or symbols, commands and results, changed files, assumptions, and unresolved concerns. The primary agent owns requirements, architecture, cross-module decisions, integration, and final acceptance.

Escalate to the primary agent when requirements or architecture are ambiguous, evidence conflicts, the same path fails twice, a task involves coordinate direction or pose propagation, atomic publication or deletion, remote side effects, training, or final acceptance. A high-risk EGS review should use the read-only `critical_reviewer` role when an independent bounded review is useful; final judgment remains with the primary agent and the user.

## Model routing

Use the configured Astra Low primary for routine decisions and coordination. Small tasks stay with one agent. For substantial work, delegate a bounded subtask only when it can run independently alongside useful primary work and improves quality or time. Do not run every role as a fixed pipeline. Keep the Windows child-agent cap at 1 and one writer per worktree, including the primary.

Use `scout` (Luna High) for narrow source discovery and deterministic evidence; `explorer` (Terra Medium) for bounded call-chain and data-flow analysis; `worker` (Sol Medium) for normal implementation; `routine_worker` (Terra Medium) for low-risk edits with a known pattern and clear checks; `reviewer` (Astra Low) for ordinary independent review; `critical_reviewer` (Astra High) for concrete algorithmic or high-risk questions. Unspecified subagents default to Sol Medium. Model and effort defaults are starting points, not proof of quality or savings.

Prefer `fork_turns="none"` for role-based delegation and pass the goal, allowed paths, constraints, acceptance checks, and escalation conditions explicitly. Custom roles pin both model and effort; do not assume spawn overrides replace them. When a different tier is needed, use a suitable role or, if the live tool supports it, an unspecialized isolated agent with both model and effort explicitly set. Full-history forks inherit the parent settings. Follow the live tool contract when capabilities differ.

Use Astra High for difficult core reasoning, coordinate/scale/gradient issues, CUDA numerics, or decisions gating costly experiments; let the primary handle core work directly when delegation would add overhead. A request to escalate is not evidence that the model or effort changed: verify the actual runtime selection, and report when it cannot be changed in place. Do not climb every effort level mechanically or default to Max, Ultra, or Fast.

Missing files, permissions, or requirements need better evidence first. Allow a repair based on new evidence, then re-diagnose if the same failure persists. Require source paths and lines, inspected scope, confirmed facts, uncertainties, and key original snippets from readers; inspect decision-critical originals before accepting a conclusion. Review against requirements and the actual diff; tests and reproducible checks determine acceptance.

Read-only roles declare read-only sandbox defaults, but live parent permission overrides can take precedence. Do not claim an isolation guarantee without checking effective permissions. Preserve the existing login/provider and Windows/WSL boundary; never switch to API-key billing, enable Fast, or launch paid experiments merely to work around usage limits.

## Development exploration and submission contract

At the start of repository work, inspect the current worktree so pre-existing user work can be preserved. This baseline is not a limit on exploration.

During development, explore freely when it helps solve the task: prototypes, alternative implementations, diagnostics, tests, notes, temporary artifacts, and authorized local WIP commits may be broader than the eventual deliverable. Keep exploratory work identifiable and reversible, and continue to respect repository boundaries, safety rules, and authorization gates. A local WIP commit is a development artifact, not approval to publish its contents.

Before pushing any branch to a remote, opening or updating a pull/merge request, requesting remote review, or handing work to another person for integration:

- derive an exact submission candidate from the requested outcome rather than from everything produced during development;
- inspect `git status` and the name-status, stat, and full branch diff from the task baseline through `HEAD`, including relevant uncommitted changes;
- keep the candidate diff to the smallest coherent task-complete change, excluding unrelated user work, abandoned alternatives, generated evidence, local notes, broad refactors, generalized infrastructure, speculative hardening, and extra deliverables that are not needed for the requested outcome; and
- preserve unselected local work instead of staging, committing, overwriting, or deleting it without authorization.

Passing tests proves behavior, not that every changed file belongs in the submission.

## Local closeout

After a mutating task is delivered, inventory task-relevant local-only state that may outlive the submission, including ignored or generated artifacts, prototypes, local branches and worktrees, and bundles or backups. Classify each known item as keep, archive, or cleanup candidate. Report the classification inventory, calling out uncertain or user-owned items separately. Treat this as a read-only review; do not delete, move, overwrite, prune, or otherwise change an item without explicit authorization for the exact targets.
