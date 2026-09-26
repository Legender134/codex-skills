# Repository Contract

Read this before designing, implementing, or reviewing work that requires the full contract. Finish discovery and resolve material conflicts, then state a concise, task-local contract in the conversation. Do not add a contract document to the repository unless explicitly required.

## Evidence precedence

Resolve binding user, repository, and organization requirements by authority and scope, subject to controlling system and developer instructions. Do not infer an exception to a binding requirement from existing code or configuration. Ask the user, citing the sources, only for an unresolved material conflict or a change beyond the authorized scope or risk; do not assume they can waive a higher-priority requirement.

Within those requirements, choose implementation conventions using build, dependency, test, format, lint, and CI configuration, then analogous nearby code/tests and recent history, then general engineering practice. Apply compatible guidance and continue within existing authorization when authority and scope resolve a conflict.

## Read-only discovery

Inspect without changing state:

- repository and relevant subproject roots;
- current branch, configured upstream, candidate base, and merge base;
- tracked, staged, unstaged, and untracked state, retaining the distinct index and worktree versions of pre-existing changes;
- root and nested instruction files governing likely paths;
- build, dependency, test, format, lint, and CI configuration;
- closest analogous code, tests, interfaces, and naming;
- relevant recent history and change granularity.

Treat all pre-existing changes as user-owned. Query remote refs without updating local refs when that supplies the needed evidence. If an authorized comparison needs missing commit objects, a targeted fetch is appropriate; record the resolved ref and commit. Do not pull, switch branches, reset, clean, or stash merely to improve discovery.

## Full contract template

Include only relevant fields:

- **Baseline:** selected repository/task base, confidence, and evidence.
- **Requested outcome:** required behavior, evidence, and non-goals.
- **Exploration boundaries:** protected user work, permitted directories, packages, interfaces, and authorization limits. These are guardrails, not an exact development file allowlist.
- **Patterns:** analogous implementation and test conventions.
- **Dependencies:** allowed placement and whether additions are justified.
- **Errors/logging:** established handling, messages, and observability.
- **Tests/commands:** required levels, style, and repository-native commands.
- **Docs/generated artifacts:** expected locations and inclusion policy.
- **Submission policy:** how the exact candidate paths will be selected from local development work.
- **Delivery conditions:** verification, review, branch, and grouping expectations.
- **Gated operations:** destructive, history-changing, or external actions requiring authorization.

Expected size, file counts, or test ratios may identify anomalies; they are never quotas.

## Special cases

- **No upstream:** retain an explicitly supplied and verified baseline. If the intended base is unknown, select an evidence-backed local mainline/history fallback, label remaining uncertainty, and ask only if that ambiguity changes the solution. Missing upstream alone does not lower confidence in an established base.
- **New or empty repository:** use minimal general conventions and surface consequential choices; do not invent process scaffolding.
- **Nested rules:** apply each instruction only within its scope; the most specific applicable repository rule governs within the repository-instruction level.
- **Dirty worktree:** preserve unrelated tracked and untracked changes. A request to continue or repair existing WIP can authorize edits in the same paths; inspect and retain that work's intent rather than treating overlap alone as a stop signal. Pause only affected edits when ownership, intended behavior, authorization, or a safe way to preserve existing work is unclear; continue independent authorized work.
- **Experiments:** exploration may create prototypes, alternatives, diagnostics, notes, or temporary files. Keep them identifiable and isolated when practical. At submission, select or migrate only the required result; preserve other local work unless cleanup is authorized.
- **Material conflict:** resolve or escalate it, then state the contract before implementation. Conflict analysis is not a substitute for the contract.

## Recheck triggers

Re-read relevant evidence and update the contract before crossing a repository boundary, changing an ordinary dependency, entering another governed subsystem, or using an unfamiliar pattern. Before introducing a heavyweight dependency or changing a public interface, review the evidence and tradeoffs. Continue when that change is already authorized; request direction only for missing necessary information, a new material risk, or scope beyond existing authorization. A larger intermediate diff or additional exploratory file alone does not require escalation.
