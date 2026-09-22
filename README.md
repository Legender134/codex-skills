# Codex Skills

Portable Codex skills and independently maintained Windows/WSL routing configuration.

## Included Skills

- `codex-sync-skills`: safely previews and creates approved symbolic links from Windows Skill installations into WSL. It protects conflicts and never copies or overwrites existing Skill destinations.
- `repository-aligned-development`: keeps repository work aligned with local instructions, established patterns, user-owned changes, minimal diffs, verification evidence, and explicit authorization gates.
- `crafting-desktop-companion-pets`: researches, recommends, builds, repairs, reviews, validates, and packages DesktopCompanion pets across the supported v2, v3, and v4 formats.
- `hatch-pet`: builds and validates Codex v2 animated pets; uses the separate Apache-2.0 license in its directory.
- `using-shared-gpu-host`: identifies ownership, allocation, and authorization boundaries for shared GPU work.
- `planned-development`: an explicit-only design, implementation planning, and review workflow; invoke it by name when useful.

## Windows / WSL routing configuration

[Setup guide](templates/codex-routing/SETUP.md) · [Installer and validation](templates/codex-routing/README.md)

The configuration uses GPT-6 Sol High for the primary and unspecified children.
Named routes use Luna Low for read-only scout supervision, Luna High for exploration
and routine edits, Luna Max for bounded implementation, Sol High for ordinary review,
and Astra High for critical review. The child cap is two per primary session.
Routing is global-only; the retired EGS project installer never writes project
overrides. Preserve existing provider/login, project domain rules and unrelated
configuration. See the routing package README for safe installation and rollback.

## Install with Codex

Ask Codex:

> Use `skill-installer` to install `skills/codex-sync-skills` and `skills/repository-aligned-development` from `Legender134/codex-skills`.

The installer places each selected directory under `$CODEX_HOME/skills` (or `~/.codex/skills` when `CODEX_HOME` is unset). Restart or reload the Codex client if the new Skills are not discovered immediately.

## DesktopCompanion Pet Studio

The pet-production workflow has two separate pieces: install the Skill for Codex guidance, then copy the project overlay into a compatible DesktopCompanion checkout.

### Install the Skill

Ask Codex:

> Use `skill-installer` to install `skills/crafting-desktop-companion-pets` from `Legender134/codex-skills`.

This installs the `crafting-desktop-companion-pets` Skill; `skill-installer` does not copy the project overlay.

### Copy the project overlay

The project overlay is source, configuration, and toolchain material, not a Skill. Copy the contents of `templates/desktop-companion-pet-studio` into the root of a compatible DesktopCompanion checkout; do not nest the directory. Merge existing `AGENTS.md` and configuration conflicts instead of overwriting user settings. Read the [detailed project overlay README](templates/desktop-companion-pet-studio/README.md) for prerequisites, setup, and verification.

The pet overlay inherits user-global routing, preserves pet-specific task briefs without installing project roles, documents Image 2.5 capabilities without changing the host's built-in image backend, and creates resumable run-state records. Approved decisions persist; internal visual checks still precede downstream production and final acceptance. No API billing or pet installation is authorized by copying the template.

## Manual Installation

Clone this repository, then copy or link the selected directory from `skills/` into the user Skill directory for the target Codex installation.

For `codex-sync-skills`, install the authoritative copy on Windows first. Run its utility inside the intended WSL distribution in preview mode, review portability, and explicitly approve any links before applying them.

## Optional global repository rules

[`agents/repository-aligned-development/AGENTS.md`](agents/repository-aligned-development/AGENTS.md) is a portable companion template for Codex's global instructions. Merge its contents into `~/.codex/AGENTS.md` when you want the repository-aligned development rules to apply across projects. Preserve any existing environment- or project-specific instructions; do not replace the whole file blindly.

The similarly named `skills/repository-aligned-development/agents/openai.yaml` is different: it contains UI metadata and the default prompt for the Skill. It is installed with the Skill and is not a global agent configuration file.

## Verify

Run the portable synchronization test suite from a Linux or WSL shell:

```bash
python3 skills/codex-sync-skills/scripts/test_sync_skills.py
```

## License

MIT, except `skills/hatch-pet`, which retains its [Apache-2.0 license](skills/hatch-pet/LICENSE.txt) and [adaptation notice](skills/hatch-pet/NOTICE.md).
