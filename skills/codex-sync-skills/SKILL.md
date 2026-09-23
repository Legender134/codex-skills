---
name: codex-sync-skills
description: Use when user-authored Codex Skills differ between Windows and WSL, a Windows Skill is missing from WSL discovery, or a WSL Skill destination or symbolic link reports a conflict.
---

# Sync Codex Skills

## Core rule

Keep Windows user-authored Skills authoritative. Preview first, review portability, and create only explicitly approved WSL symbolic links. Never copy Skill contents or replace an existing destination.

## Run a preview

Run the utility inside the intended WSL distribution. Do not assume a distribution name or account name.

- From Windows, list distributions with `wsl.exe --list --quiet`. Choose the target or ask if ambiguous. Convert the installed script path with `wsl.exe -d <distribution> wslpath -u <windows-script-path>`, then run it with `wsl.exe -d <distribution> python3 <wsl-script-path>`.
- From WSL, run `python3 <skill-path>/scripts/sync_skills.py` from the installed Skill.

The utility infers profiles from its installed source path and current WSL user. Inferred-root mode rejects non-WSL execution; use `--help` and all four explicit roots for testing or a nonstandard layout.

Relative root paths are resolved from the command's working directory before planning links. `--skill` limits discovery and root validation to the selected scopes. Without selectors, inspect both scopes. An absent inferred Windows source is an empty scope; still check any existing WSL destination for broken links. Explicit roots in an inspected scope must exist, and an existing source requires a WSL destination directory. Preview never creates directories.

Show the complete output, including the selector, source, and destination. Preview mode must not mutate the filesystem. Interpret statuses as follows:

| Status | Meaning |
|---|---|
| `CREATE` | Preview found a missing WSL destination. |
| `CREATED` | Apply mode created the selected symbolic link. |
| `UNCHANGED` | The destination already links to the expected source. |
| `CONFLICT` | An existing destination is protected and was not changed. |

Add `--json` when another tool must consume the result. It emits `actions` with selector, source, destination, status, and detail fields, plus an `issues` list.

`BROKEN_LINK` issues also report existing destination links whose target has no readable `SKILL.md`, even when the Windows source is absent. Preview never repairs or unlinks them.

Exit codes are stable: `0` means a safe result, `1` means a usage/environment error, and `2` means at least one conflict or rejected candidate.

## Review portability

Before applying each `CREATE` action:

1. Read the candidate `SKILL.md` completely.
2. Inventory its bundled scripts and required tools.
3. Classify it as portable, Windows-specific, or ambiguous.
4. Keep Windows-specific Skills Windows-only. Explain ambiguous dependencies and request direction.

A symbolic link makes instructions discoverable; it does not make Windows executables, drive paths, or PowerShell-only tooling run on Linux.

## Request approval

Present the portable selectors, sources, and destinations in the preview. Reuse existing user authorization that covers those targets; ask only when the scope is still ambiguous or a new action exceeds it. A preview or general sync request never authorizes overwriting conflicts.

## Apply approved links

Run `--apply` with one repeated `--skill SCOPE/NAME` per approved candidate. Use `--all` only when every eligible candidate was explicitly approved. Use `--help` for root syntax.

After applying, expect each newly linked selection to report `CREATED`. Preview again and verify every selected entry is `UNCHANGED`. If any entry is `CONFLICT`, report its exact path and leave it untouched; resolving or replacing it requires a separate user decision.

Discovery and apply exclude `.system` from source and destination paths, including aliases. Sources and `SKILL.md` links must also stay inside the approved source root. An existing destination link must address the selected source path; an alternative alias is a conflict even if it currently resolves to the same directory. Apply rechecks the planned root directories, selected source identity, `SKILL.md` identity/content, and expected links, including entries planned as `UNCHANGED`. Failed rechecks become `CONFLICT`; a correct link created by another process can be `UNCHANGED`. These checks cover one invocation, not a saved approval snapshot or an immutable skill bundle; links remain live references to Windows content after verification.

Creation is bound to the verified destination directory handle, so replacing its path cannot redirect the write into another directory. This requires directory-relative symlink support; unsupported hosts refuse creation and should run the utility through WSL. Keep the source and destination directories stable during apply: a concurrent rename can still move the original directory or invalidate the result, which is reported as `CONFLICT` without cleanup.

`CREATED` requires a readable `SKILL.md` through the new link. If that check fails after creation, report `CONFLICT` and preserve the link for inspection; do not silently remove it or report success.

## Exclusions

Always exclude `.system`, plugin caches, MCP configuration, `config.toml`, authentication, sessions, logs, and all other Codex state. Never delete, move, copy, unlink, overwrite, or repair entries during this workflow.
