# DesktopCompanion Pet Studio overlay

This directory is an overlay, not a standalone project. Copy its contents into the root of a compatible DesktopCompanion checkout. Do not nest the `desktop-companion-pet-studio` directory inside that checkout. Review destination-file conflicts first: merge `AGENTS.md` and any toolchain conflicts with existing files rather than replacing them blindly. Do not copy an installed application's binaries or personal pet run into the shared repository.

## Prerequisites

- Windows x64 and PowerShell 7.
- Signed Python 3.12 for the locked toolchain runtime.
- An explicit Python 3.12 interpreter with PySide6 installed for the Qt WebP oracle.

## Model routing

The overlay inherits model, effort, role and concurrency settings from user-global Codex configuration. It installs no `.codex/config.toml` or `.codex/agents/` overrides. Keep one writer and follow the global child cap. Preserve provider, login, billing and permission settings.

Three version-neutral business briefs live under `docs/agent-briefs/`:

- `pet-researcher.toml`: source inventory, version recommendation and format confirmation; pass as context to a suitable global read-only exploration role.
- `pet-builder.toml`: build only the confirmed package version; pass as context to a suitably scoped global worker.
- `pet-reviewer.toml`: independent selected-version review; pass as context to a global reviewer or critical reviewer as warranted.

These TOML files are task context, not auto-discovered agent definitions. Their sandbox preferences describe task boundaries, not permission enforcement. Do not copy them into an active agents directory. The primary supplies exact paths, scope and acceptance checks along with the relevant brief.

The briefs follow the separately installed `crafting-desktop-companion-pets` Skill and its handoff contracts. The overlay intentionally contains no project-local pet Skill; install the global Skill first.

Check live role availability and effective permissions when delegating; a TOML declaration alone does not prove either. Existing accepted style, format and scope do not need repeated confirmation on resume. Internal QA still applies, and user acceptance of a particular image remains separate.

## Image generation and resuming a pet

Use the host's built-in image generation by default. The installed pet Skill's [execution and model guide](../../skills/crafting-desktop-companion-pets/references/execution-and-models.md) records Image 2.5 Sunburst/Flare API capabilities, size/alpha constraints and reference-preserving iteration. That repository link is for browsing before copying; after installation, read `references/execution-and-models.md` inside the installed Skill.

This overlay does not select the built-in tool's image model, install an API SDK or replace `.system/imagegen`. A host with an older CLI may need a separately authorized update. API generation and its billing require explicit authorization; installing this overlay is not that authorization.

Ask Codex to create a separate run using the installed Skill's `prepare_pet_run.py`. New runs include `production-state.json` alongside the existing evidence, identity, jobs and summary contracts. The state starts without approvals or observed model claims; populate it from the actual user's decisions and tool results. On resume, read that state and the linked evidence, reuse passing work, and update the next action and blockers. An existing run can retain its own equivalent state record. This index is not a visual, package or runtime validator.

Example request after setup:

> 使用 crafting-desktop-companion-pets，为我制作一个原创云朵猫桌宠。先研究当前 DesktopCompanion 支持的格式并给出建议；记录我确认的风格和范围，之后通过内部检查就继续制作，不要重复询问同一确认。只制作本地候选包，不安装、不发布、不切换 API 计费。

The workflow supports v2/v3/v4; do not copy another pet's dimensions or action quotas. Validate the exact selected-format package root and bytes you intend to hand off. In v3 the package directory name must match the pet ID.

The overlay contains no project routing configuration. Codex trust remains user-global and path-specific: add trust only for the exact local checkout path in the user configuration, never for a parent directory or wildcard, and never add a `[projects]` section to this overlay. Likewise, add only the exact checkout path to Git's global safe-directory list; do not use `safe.directory=*`:

```powershell
git config --global --add safe.directory '<exact-checkout-path>'
```

The optional `repository-aligned-development` global guidance remains a separate Codex Skill; do not duplicate it into this overlay.

## Setup and verification

From the compatible DesktopCompanion checkout root, set the explicit PySide6 Python path and run setup, then the read-only verifier:

```powershell
$qtPython = 'C:\path\to\PySide6\python.exe'
& .\scripts\setup_pet_toolchain.ps1 -QtPython $qtPython
& .\scripts\verify_pet_toolchain.ps1 -QtPython $qtPython
```

Require setup to report `Installed and published pet toolchain <lockDigest>.` (or, on an unchanged repeat, `Pet toolchain <lockDigest> is already current.`). Require verification to end with `PET TOOLCHAIN VERIFIED`.

Plan for approximately 1.01 GB of locked offline payload after adding the official RIFE 20221029 archive, and approximately 1.90 GB for each installed version. The overlay tracks source and metadata only; downloaded tools, models, caches, and installed environments stay machine-local.

See the [detailed operator guide](docs/development-pet-toolchain.md) for toolchain behavior, verification gates, and operational constraints.
