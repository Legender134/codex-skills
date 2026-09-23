# WSL global routing instructions

WSL is the primary environment for Linux development, Git, tests, builds, data processing, remote-job orchestration, and integration. Windows owns native applications and GUI tooling. Use the environment responsible for the task; keep credentials, providers, and native tooling separate.

Treat the configured per-session child limit as a ceiling, not a target; live tool limits also apply.

Delegated work must return distilled evidence: the question answered, source paths and lines, changed files, checks and results, assumptions, and unresolved concerns. The primary agent owns requirements, architecture, integration, and final acceptance.

## Delegation and model routing

Keep simple, low-risk work with the primary. Decide delegation by complexity, risk, independence, and expected benefit, not file count. Even a single-file change may justify an independent high-risk review. Delegate only a bounded task that can run alongside useful primary work; do not run roles as a fixed pipeline. Keep one writer per worktree, including the primary, and serialize changes to shared repository state.

Read live role bindings and descriptions before dispatch. Use reviewer for ordinary independent review and critical_reviewer for substantial correctness risks requiring deeper analysis; domain keywords alone do not determine risk. Cross-module decisions and high-risk implementation remain with the primary.

Prefer `fork_turns="none"` and supply the goal, scope, constraints, acceptance checks, and escalation conditions. Custom roles pin model and effort; full-history forks inherit parent settings. Follow the live tool contract, report the returned agent identifier and route concisely, and distinguish configured model/effort from runtime-verified values. A routing request alone does not prove a change took effect.

Use configured GPT-6 routes without GPT-5.6 fallbacks. If a route is unavailable, report it and use another supported GPT-6 route only when appropriate. Avoid automatic effort escalation; follow the role's configured effort. Never switch provider/login, use API-key billing, enable Fast, or start paid experiments to bypass usage limits.

Read-only roles remain behaviorally read-only even if inherited permissions are broader; do not claim sandbox isolation without verification.

## Authority and escalation

Child agents stop the affected work and report to the primary when scope or architecture is unclear, evidence conflicts, or the same failure persists after an evidence-based repair. They do not decide high-risk correctness, publication, destructive data operations, remote mutations, job control, or final acceptance. Routine read-only monitoring does not itself require escalation.

The primary resolves escalations and continues independent authorized work. Ask the user only when necessary information or authorization is missing, or a material change exceeds the approved scope or risk. Reuse authorization already granted in the session for the same action and targets; do not request it again solely because a skill, phase, or agent changed. Do not guess critical requirements or weaken checks. Verify decision-critical original evidence before accepting reports.

## Monitoring

Assign scout exact job identities, allowed paths and read-only commands, expected stages, completion criteria, heartbeat and maximum silence intervals. While coverage is healthy, avoid duplicate routine polling; verify original evidence at planned checkpoints and final acceptance.

Track the last heartbeat and check agent/message status when the maximum silence interval expires. If coverage ends or cannot be verified, resume necessary read-only checks and report the gap; never depend on a failed scout to report its own failure or imply supervision continues after it ends. Monitoring does not authorize job control, repairs, or publication; the primary retains those decisions within the user's authorization.

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
