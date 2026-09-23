# Submission Checklist

Use this for review, completion, and submission preparation. Submission is a verification step, not the first repository-alignment check.

## Inspect the complete change

- Record the task baseline, exact candidate, target remote/branch, and PR/MR base when applicable. Inspect full status and the task-baseline diff.
- Verify the target remote ref against fresh evidence; do not assume a cached tracking ref is current. Inspect every commit the push would publish, including commits already present at task start, and the actual proposed PR/MR diff against its target base. These can differ from the task-baseline diff.
- Inspect the complete tracked diff. Inventory untracked paths and their ownership; inspect the contents of submission candidates and files needed to assess the change. Unrelated datasets, logs, and generated artifacts need only a path-level inventory unless evidence makes their contents relevant.
- Distinguish the whole worktree from the exact submission candidate; local exploratory work may remain unselected.
- If unrelated outgoing commits are present, isolate the task-complete candidate without rewriting or discarding user history. For multiple remotes, verify each destination and its intended content separately.
- Check for secrets, credentials, machine-specific paths, dead code, duplicate or competing implementations, broad formatting churn, and abandoned artifacts.
- Confirm each file has a repository- and task-based purpose; treat line/file/test ratios only as anomaly signals.

## Verify behavior and alignment

- Run repository-native format, lint, unit, integration, and build checks in proportion to risk.
- Record fresh commands, exit status, and relevant results. Never imply an unrun check passed.
- Compare the final diff with the task-local repository contract.
- Report justified deviations, unresolved gaps, environment-dependent behavior, and any overlap with user-owned work.

## Delivery report

Report:

- changed files and purpose;
- fresh verification commands and results;
- unverified behavior or validation gaps;
- task and design links when they exist;
- recommended commit grouping when a commit or submission is requested, or grouping materially improves reviewability;
- known merge conditions when they apply, including repository and applicable organization requirements.

Keep the selected submission content minimal and reviewable. Preserve unselected local work; metrics do not authorize mechanical deletion.

## Local closeout

After a mutating task is delivered, inspect task-relevant local-only state that may outlive the submission, including unselected tracked, untracked, or ignored files; generated evidence and prototypes; local branches and worktrees; and bundles or backups.

Classify each known item as **keep**, **archive**, or **cleanup candidate**. Report the classification inventory, calling out uncertain or user-owned items separately. This classification is read-only: do not delete, move, overwrite, prune, or otherwise change any item without explicit authorization for the exact targets.

## Authorization gate

Before deletion or material overwrite/move, branch or history rewrite, commit, push, merge-request/pull-request creation, or any external mutation, check whether the user's existing authorization covers the action and exact targets. Proceed when it does; stop and ask only for missing authorization or a material change in scope or risk. If cleanup is desired but unauthorized, preserve the current work and propose a clean branch with selective migration.
