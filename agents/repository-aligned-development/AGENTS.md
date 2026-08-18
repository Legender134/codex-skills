# Repository development defaults

At the start of repository work, inspect the current worktree so pre-existing user work can be preserved. This baseline is not a limit on exploration.

During development, explore freely when it helps solve the task: prototypes, alternative implementations, diagnostics, tests, notes, temporary artifacts, and authorized local WIP commits may be broader than the eventual deliverable. Keep exploratory work identifiable and reversible, and continue to respect repository boundaries, safety rules, and authorization gates. A local WIP commit is a development artifact, not approval to publish its contents.

Before pushing any branch to a remote, opening or updating a pull/merge request, requesting remote review, or handing work to another person for integration:

- derive an exact submission candidate from the requested outcome rather than from everything produced during development;
- inspect `git status` and the name-status, stat, and full branch diff from the task baseline through `HEAD`, including relevant uncommitted changes;
- keep the candidate diff to the smallest coherent task-complete change, excluding unrelated user work, abandoned alternatives, generated evidence, local notes, broad refactors, generalized infrastructure, speculative hardening, and extra deliverables that are not needed for the requested outcome; and
- preserve unselected local work instead of staging, committing, overwriting, or deleting it without authorization.

Passing tests proves behavior, not that every changed file belongs in the submission.

After a mutating task is delivered, inventory task-relevant local-only state that may outlive the submission, including ignored or generated artifacts, prototypes, local branches and worktrees, and bundles or backups. Classify each known item as keep, archive, or cleanup candidate. Report the classification inventory, calling out uncertain or user-owned items separately. Treat this as a read-only review; do not delete, move, overwrite, prune, or otherwise change an item without explicit authorization for the exact targets.
