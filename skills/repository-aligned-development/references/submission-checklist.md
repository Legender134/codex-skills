# Submission Checklist

Use this for review, completion, and submission preparation. Submission is a verification step, not the first repository-alignment check.

## Inspect the complete change

- Select and name the evidence-backed base; inspect full status and the complete diff against it.
- Inspect every changed and untracked file, plus unusually large and generated files.
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

Keep proposed submission content minimal and reviewable. Metrics do not authorize mechanical deletion.

## Authorization gate

Stop and obtain explicit authorization before deletion or material overwrite/move, branch or history rewrite, commit, push, merge-request/pull-request creation, or any external mutation. If cleanup is desired but unauthorized, preserve the current work and propose a clean branch with selective migration.
