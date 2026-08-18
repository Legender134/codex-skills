# Repository Contract

Read this before designing, implementing, or reviewing work that requires the full contract. Finish discovery and resolve material conflicts, then state a concise, task-local contract in the conversation. Do not add a contract document to the repository unless explicitly required.

## Evidence precedence

1. Explicit user instruction for the current task.
2. Authoritative repository instructions, including scoped or nested rules.
3. Build, dependency, test, format, lint, and CI configuration.
4. Analogous nearby code/tests and recent history.
5. Applicable organization policy.
6. General engineering practice.

Higher evidence controls. Apply compatible lower-level guidance. If a conflict materially changes scope, architecture, dependencies, or delivery risk, cite the evidence and ask the user; otherwise choose the conservative repository-aligned interpretation.

## Read-only discovery

Inspect without changing state:

- repository and relevant subproject roots;
- current branch, configured upstream, candidate base, and merge base;
- tracked, modified, and untracked state;
- root and nested instruction files governing likely paths;
- build, dependency, test, format, lint, and CI configuration;
- closest analogous code, tests, interfaces, and naming;
- relevant recent history and change granularity.

Treat all pre-existing changes as user-owned. Do not fetch, pull, switch branches, reset, clean, or stash merely to improve discovery.

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

- **No upstream:** select an evidence-backed local mainline/history baseline, label it lower confidence, and ask if ambiguity changes the solution.
- **New or empty repository:** use minimal general conventions and surface consequential choices; do not invent process scaffolding.
- **Nested rules:** apply each instruction only within its scope; the most specific applicable repository rule governs within the repository-instruction level.
- **Dirty worktree:** preserve unrelated tracked and untracked changes; isolate planned paths and stop if required edits materially overlap user work.
- **Experiments:** exploration may create prototypes, alternatives, diagnostics, notes, or temporary files. Keep them identifiable and isolated when practical. At submission, select or migrate only the required result; preserve other local work unless cleanup is authorized.
- **Material conflict:** resolve or escalate it, then state the contract before implementation. Conflict analysis is not a substitute for the contract.

## Recheck triggers

Re-read relevant evidence and update the contract before crossing a repository boundary, changing an ordinary dependency, entering another governed subsystem, or using an unfamiliar pattern. Before introducing a heavyweight dependency or public interface, pause, present the evidence and tradeoffs, and request user direction. A larger intermediate diff or additional exploratory file alone does not require escalation.
