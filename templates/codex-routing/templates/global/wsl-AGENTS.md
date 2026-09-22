# WSL global routing instructions

The WSL environment is the primary development environment for Git, tests, builds, data processing, GPU and remote-training orchestration, and integration work. Keep WSL and Windows duties independent.

Do not delegate trivial questions, explanations, single-file changes, single-command checks, or work whose scope is not yet clear. The user-level WSL child-agent concurrency limit is **2 per primary session**, excluding the primary; it is not a machine-wide pool shared across sessions. Maintain this setting globally, without project overrides. This is a ceiling, not a requirement to spawn two agents. When useful, one slot may supervise an authorized job through read-only `scout` while the other handles an independent bounded implementation, exploration, or review task. Never run overlapping writers or allow two roles to modify the same files or repository state; keep one writer per worktree, including the primary.

Delegated work must return distilled evidence: the question answered, relevant paths or symbols, commands and results, changed files, assumptions, and unresolved concerns. The primary agent owns requirements, architecture, cross-module decisions, integration, and final acceptance.

Escalate to the primary agent when requirements or architecture are ambiguous, evidence conflicts, the same path fails twice, a task involves coordinate direction or pose propagation, atomic publication or deletion, remote side effects, training control or strategy, or final acceptance. Read-only supervision of an explicitly scoped training or preprocessing job belongs to `scout` and does not itself require escalation; job control, diagnosis, and acceptance still do. A high-risk EGS review should use the read-only `critical_reviewer` role when an independent bounded review is useful; final judgment remains with the primary agent and the user.

## Model routing

Keep model and reasoning bindings in the user-level `~/.codex/config.toml` and `~/.codex/agents/*.toml` only. Project `AGENTS.md` files retain domain contracts and safety rules, not duplicated model tables; do not create project model, role, or concurrency overrides unless the user explicitly changes this policy. Preserve project-specific hooks, skills, state, and other unrelated files.

Use the configured primary for routine decisions, implementation, and coordination. Small tasks stay with one agent. For substantial work, delegate a bounded subtask only when it can run independently alongside useful primary work and improves quality or time. Do not run every role as a fixed pipeline. Follow the global child-agent cap and keep one writer per worktree, including the primary.

Use `scout` for narrow source discovery and read-only ongoing supervision of training, preprocessing, reconstruction, fusion/alignment, dataset preparation, evaluation, rendering/export, builds, tests, and other authorized pipelines; `explorer` for bounded call-chain and data-flow analysis; `worker` for bounded implementation with explicit requirements and reproducible acceptance checks; `routine_worker` for low-risk edits with a known pattern and clear checks; `reviewer` for ordinary independent review; and `critical_reviewer` for concrete algorithmic or high-risk questions. Complex cross-module analysis, integration, and high-risk implementation stay with the primary. Model and effort defaults are starting points, not proof of quality or savings.

Do not select any GPT-5.6 model, including aliases, fallbacks, resumed jobs, or explicit child overrides. Use the configured GPT-6 routes; if one is unavailable, report that fact and select another supported GPT-6 route only when its capability and cost fit the task. Do not silently revert to an older family or edit historical records and provider-managed model caches to hide old model names.

Prefer `fork_turns="none"` for role-based delegation and pass the goal, allowed paths, constraints, acceptance checks, and escalation conditions explicitly. Custom roles pin both model and effort; do not assume spawn overrides replace them. When a different tier is needed, use a suitable role or, if the live tool supports it, an unspecialized isolated agent with both model and effort explicitly set. Full-history forks inherit the parent settings. Follow the live tool contract when capabilities differ.

Use the configured `critical_reviewer` for difficult coordinate/scale/gradient issues, CUDA numerics, or decisions gating costly experiments when an independent review is useful. Let the primary handle core work directly when suitably configured and delegation would add overhead. A request to escalate is not evidence that the model or effort changed: verify the actual runtime selection, and report when it cannot be changed in place. Do not climb every effort level mechanically or apply Max to every role; the explicitly configured bounded `worker` may use Max. Do not default to Ultra or Fast. Simpler primary tasks may use a supported lower-effort route when explicitly selected and verified; high-risk work need not pass through cheaper roles first.

For monitoring, give `scout` exact job identities and allowed paths/commands, expected stages, cadence, and completion criteria. It may continuously collect timestamped progress, log freshness, metrics, checkpoint/output presence, resource use, and exit status, with concise changes, agreed heartbeats, and prompt anomaly reports. Use deterministic commands and supported wait/recurring-monitoring mechanisms rather than repeatedly sending full logs through agents. Unchanged state alone is not a reason to stop; an ended monitoring turn must explicitly hand off pending checks rather than claim background supervision. The primary owns user-facing updates and final acceptance. Monitoring roles must never start, stop, pause, resume, restart, retry, or reconfigure processes, alter parameters or data, repair code, or publish outputs; anomalies are escalated with original evidence. Judge routing by correctness, rework, elapsed time, and total usage, not token unit price alone.

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
