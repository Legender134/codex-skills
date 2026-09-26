# Submission Checklist

Use this for review, completion, and submission preparation. Submission is a verification step, not the first repository-alignment check.

## Inspect the complete change

- Record the task baseline and exact candidate, plus integration base, destination remote/branch, and PR/MR base when applicable. For local-only delivery, mark remote checks inapplicable; do not invent a destination or require remote access.
- Inspect the actual deliverable against the integration base, including earlier commits or dependencies it carries. For a local patch or bundle, verify the reconstructed candidate on that base in an isolated workspace when needed; tests in the source worktree do not establish applicability or completeness for a different receiving base.
- For remote publication, verify the target remote ref against fresh evidence; do not assume a cached tracking ref is current. A remote-ref query establishes identity, not commit contents; if objects needed for comparison are missing, obtain them within existing authorization before claiming the comparison is complete. Inspect every commit the push would publish, including commits already present at task start, and the actual proposed PR/MR diff against its target base when applicable. These can differ from the task-baseline diff.
- Inspect full status and the task-baseline diff, plus staged and unstaged diffs separately. Before committing, verify that the exact content to be recorded matches the intended candidate while preserving unrelated staged and unstaged work. Inventory untracked paths and their ownership; inspect the contents of submission candidates and files needed to assess the change. Unrelated datasets, logs, and generated artifacts need only a path-level inventory unless evidence makes their contents relevant.
- Distinguish the whole worktree from the exact submission candidate; local exploratory work may remain unselected.
- If unrelated outgoing commits are present, isolate the task-complete candidate without rewriting or discarding user history. For multiple remotes, verify each destination and its intended content separately.
- Check for secrets, credentials, machine-specific paths, dead code, duplicate or competing implementations, broad formatting churn, and abandoned artifacts.
- Confirm each file has a repository- and task-based purpose; treat line/file/test ratios only as anomaly signals.

## Verify behavior and alignment

- Run repository-native format, lint, unit, integration, and build checks in proportion to risk on the final selected candidate. If it was migrated, cherry-picked, regrouped, or changed after verification, rerun affected checks in its final location; broaden them only when the changes or failures justify it. A metadata-only commit change with the same tested tree and environment does not by itself require repeating checks.
- Ensure validation does not depend on excluded tracked, untracked, or ignored work. When that cannot be established in the development worktree, use an isolated candidate and reproduce required setup there without copying unexplained local artifacts.
- Record the tested commit and any uncommitted candidate state, location, fresh commands, exit status, and relevant results. Never imply an unrun check passed or attribute original-worktree results to an untested candidate. Report blocked checks as validation gaps.
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

Apply the authorization categories in [SKILL.md](../SKILL.md#authorization-gates). Proceed when existing authorization covers the action and targets; ask only for missing necessary information or authorization, or a material change in scope or risk. If cleanup is desired but unauthorized, preserve the current work and propose a clean branch with selective migration.
