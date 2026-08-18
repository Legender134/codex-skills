# Submission Checklist

Use this for review, completion, and submission preparation. Submission is a verification step, not the first repository-alignment check.

## Inspect the complete change

- Select and name the evidence-backed base; inspect full status and the complete diff against it.
- Inspect every changed and untracked file, plus unusually large and generated files.
- Distinguish the whole worktree from the exact submission candidate; local exploratory work may remain unselected.
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

Stop and obtain explicit authorization before deletion or material overwrite/move, branch or history rewrite, commit, push, merge-request/pull-request creation, or any external mutation. If cleanup is desired but unauthorized, preserve the current work and propose a clean branch with selective migration.
