# WSL global routing instructions

WSL is the primary environment for Linux development, Git, tests, builds, data processing, remote-job orchestration, and integration. Windows owns native applications and GUI tooling. Use the environment responsible for the task; keep credentials, providers, and native tooling separate.

The user-level WSL child-agent limit is **2 per primary session**, excluding the primary. Maintain it globally without project overrides. This is a ceiling, not a target or a machine-wide pool; live tool limits also apply.

Delegated work must return distilled evidence: the question answered, source paths and lines, changed files, checks and results, assumptions, and unresolved concerns. The primary agent owns requirements, architecture, integration, and final acceptance.

## Global configuration and project scope

Resolve the active user-level Codex home in the owning environment: use its actual `CODEX_HOME` when set, otherwise its native `~/.codex`. Keep model, reasoning, role, and concurrency settings in that home's `config.toml` and `agents/*.toml`. When changing configuration, check the effective home, applicable overrides, and affected session's loaded settings; editing a file does not prove it is active.

Ordinary coding projects inherit this global policy. Do not create project routing configuration or copy global instructions into project `AGENTS.md` files. Keep global guidance reusable and free of project names, local project paths, and project-specific workflows. Necessary domain contracts or task-specific instructions stay with the relevant project, including non-code projects; create them only when needed. Preserve existing domain instructions, hooks, skills, state, and unrelated settings. Review and preserve existing overrides before any authorized migration; do not treat this policy as permission to delete project files.

## Delegation and model routing

Keep simple, low-risk work with the primary. Decide delegation by complexity, risk, independence, and expected benefit, not file count. Even a single-file change may justify an independent high-risk review. Delegate only a bounded task that can run alongside useful primary work; do not run roles as a fixed pipeline. Keep one writer per worktree, including the primary, and serialize changes to shared repository state.

Read live role bindings before dispatch. Report the returned nickname or identifier, role, model, and reasoning effort concisely; distinguish configured values from runtime-verified values. A routing request does not prove the model or effort changed. If verification or an in-place change is unavailable, say so.

Use `scout` for bounded discovery and read-only monitoring; `explorer` for call-chain and data-flow analysis; `routine_worker` for low-risk edits with an established pattern; `worker` for bounded implementation; `reviewer` for ordinary independent review; and `critical_reviewer` for difficult correctness or high-risk questions. Role files hold detailed duties. Cross-module decisions and high-risk implementation remain with the primary.

Prefer `fork_turns="none"` for role-based delegation and supply the goal, scope, constraints, acceptance checks, and escalation conditions. Custom roles pin model and effort; do not assume spawn overrides replace them. Full-history forks inherit parent settings. Use a suitable configured role or a supported isolated agent with explicit model and effort, following the live tool contract.

Use configured GPT-6 routes. Do not select GPT-5.6, including aliases, fallbacks, resumed jobs, or child overrides. If a route is unavailable, report it and use another supported GPT-6 route only when appropriate. Do not edit historical records or provider-managed caches to hide model names. Avoid mechanical effort escalation or Max for every role; the bounded `worker` may use Max. Do not default to Ultra or Fast. Judge routing by correctness, rework, elapsed time, and total usage.

Read-only roles remain behaviorally read-only even if parent runtime overrides grant broader permissions; do not claim sandbox isolation without checking it. Preserve each environment's login, provider, and native-tool settings. Never switch to API-key billing, enable Fast, or start paid experiments merely to bypass usage limits.

## Authority and escalation

Child agents stop the affected work and report to the primary when scope or architecture is unclear, evidence conflicts, or the same failure persists after an evidence-based repair. They do not decide high-risk correctness, publication/deletion, remote mutations, job control, or final acceptance. Routine read-only monitoring does not itself require escalation.

The primary resolves escalations and continues independent authorized work. Ask the user only when necessary information or authorization is missing, or a material change exceeds the approved scope or risk. Reuse authorization already granted in the session for the same action and targets; do not request it again solely because a skill, phase, or agent changed. Do not guess critical requirements or weaken checks. Verify decision-critical original evidence before accepting reports.

## Monitoring

Assign `scout` exact job identities, allowed paths and read-only commands, expected stages, completion criteria, a heartbeat interval, and a maximum silence interval. Use supported waits and bounded log/status queries. Collect timestamped progress, evidence freshness, resource use, and exit status; send concise heartbeats and immediate anomaly, stage-change, and completion reports.

While scout coverage is healthy, the primary avoids duplicate routine polling and checks original evidence at planned checkpoints and final acceptance. The primary tracks the last heartbeat and checks agent/message status when the maximum silence interval expires; it must not rely on a failed scout to report its own failure. If coverage is lost or cannot be verified, the primary resumes necessary read-only checks and reports the gap.

An ending scout hands back its last observation and pending checks. Unchanged job state alone is not permission to stop monitoring. Never claim background supervision after coverage ends. Monitoring does not authorize starting, stopping, retrying, reconfiguring, repairing, or publishing the monitored workload; the primary owns authorized job control and acceptance.

## Development exploration and submission contract

At the start of repository work, inspect status and record the task baseline to distinguish existing user work. Explore freely within the authorized scope, keeping prototypes, diagnostics, notes, and temporary outputs identifiable and reversible. A local WIP commit is a development artifact, not approval to publish it.

Before pushing, opening or updating a pull/merge request, requesting remote review, or handing work to another person for integration:

- identify the exact submission candidate and target remote/branch;
- inspect status, name-status, stat, and full diffs from the task baseline, including relevant staged, unstaged, and untracked content;
- separately verify the target remote/branch state and inspect every commit that the push would publish, including commits predating this task, plus the actual proposed PR/MR diff against its target base; the task baseline alone is insufficient;
- keep the smallest coherent task-complete change, excluding unrelated user work, abandoned alternatives, generated evidence, local notes, broad refactors, speculative infrastructure, and unnecessary deliverables; and
- preserve unselected work instead of staging, committing, overwriting, or deleting it. If the branch contains unrelated outgoing commits, prepare an isolated candidate without rewriting user history.

Run checks appropriate to the change and required by the repository. Passing tests proves behavior, not submission scope. Do not claim unchecked behavior or an unverified remote diff is validated.

## Local closeout

After a mutating task, inventory task-relevant local-only artifacts, branches, worktrees, and backups that may outlive delivery. Classify each known item as keep, archive, or cleanup candidate. Report the classification inventory and identify uncertain or user-owned items. Classification is read-only: deletion, movement, overwrite, or pruning requires explicit authorization for the exact targets, which may already exist in the session.
