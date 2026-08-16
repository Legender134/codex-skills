# Codex Skills

Portable, user-authored Skills for Codex.

## Included Skills

- `codex-sync-skills`: safely previews and creates approved symbolic links from Windows Skill installations into WSL. It protects conflicts and never copies or overwrites existing Skill destinations.
- `repository-aligned-development`: keeps repository work aligned with local instructions, established patterns, user-owned changes, minimal diffs, verification evidence, and explicit authorization gates.

## Install with Codex

Ask Codex:

> Use `skill-installer` to install `skills/codex-sync-skills` and `skills/repository-aligned-development` from `Legender134/codex-skills`.

The installer places each selected directory under `$CODEX_HOME/skills` (or `~/.codex/skills` when `CODEX_HOME` is unset). Restart or reload the Codex client if the new Skills are not discovered immediately.

## Manual Installation

Clone this repository, then copy or link the selected directory from `skills/` into the user Skill directory for the target Codex installation.

For `codex-sync-skills`, install the authoritative copy on Windows first. Run its utility inside the intended WSL distribution in preview mode, review portability, and explicitly approve any links before applying them.

## Verify

Run the portable synchronization test suite from a Linux or WSL shell:

```bash
python3 skills/codex-sync-skills/scripts/test_sync_skills.py
```

## License

MIT
