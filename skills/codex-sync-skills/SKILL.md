---
name: codex-sync-skills
description: Use when Windows and WSL Codex installations need the same user-authored Skills, or when a Skill added or changed on Windows needs WSL discovery, portability, symbolic-link, or conflict inspection.
---

# Sync Codex Skills

## Core rule

Keep Windows user-authored Skills authoritative. Preview first, review portability, and create only explicitly approved WSL symbolic links. Never copy Skill contents or replace an existing destination.

## Preview

Run the utility inside the intended WSL distribution. Do not assume a distribution name or account name.

- From Windows, list distributions with `wsl.exe --list --quiet`. Select the target explicitly; if multiple distributions are plausible and the user did not choose one, request direction. Locate the installed script under the current Windows profile in `.codex\skills` or `.agents\skills`, convert that path with `wsl.exe -d <distribution> wslpath -u <windows-script-path>`, then run it with `wsl.exe -d <distribution> python3 <wsl-script-path>`.
- From WSL, locate the installed Skill under the current user's `.codex/skills` or `.agents/skills` directory and run `python3 <skill-path>/scripts/sync_skills.py`.

The utility infers the Windows profile from its installed source path and the WSL profile from the current WSL user. Run it from an installed Skill location; use `--help` and explicit root options for a nonstandard layout.

Show the complete output. Interpret `CREATE` as a missing WSL link, `UNCHANGED` as an already-correct link, and `CONFLICT` as a protected existing entry. Preview mode must not mutate the filesystem.

## Review portability

Before applying each `CREATE` action:

1. Read the candidate `SKILL.md` completely.
2. Inventory its bundled scripts and required tools.
3. Classify it as portable, Windows-specific, or ambiguous.
4. Keep Windows-specific Skills Windows-only. Explain ambiguous dependencies and request direction.

A symbolic link makes instructions discoverable; it does not make Windows executables, drive paths, or PowerShell-only tooling run on Linux.

## Request approval

Present each portable selector, Windows source, and WSL destination. Wait for explicit authorization before using `--apply`. A previous preview or general synchronization request does not authorize overwriting conflicts.

## Apply approved links

Run the same utility with `--apply` and one repeated `--skill SCOPE/NAME` argument per approved candidate. Use `--all` only when the user explicitly approved every eligible candidate. Run `python3 scripts/sync_skills.py --help` for root override syntax.

After applying, preview again and verify every selected entry is `UNCHANGED`. If any entry is `CONFLICT`, report its exact path and leave it untouched; resolving or replacing it requires a separate user decision.

## Exclusions

Always exclude `.system`, plugin caches, MCP configuration, `config.toml`, authentication, sessions, logs, and all other Codex state. Never delete, move, copy, unlink, overwrite, or repair entries during this workflow.
