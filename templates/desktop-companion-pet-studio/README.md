# DesktopCompanion Pet Studio overlay

This directory is an overlay, not a standalone project. Copy its contents, including the hidden `.codex` directory, into the root of a compatible DesktopCompanion checkout. Do not nest the `desktop-companion-pet-studio` directory inside that checkout. Review any destination-file conflicts before copying.

## Prerequisites

- Windows x64 and PowerShell 7.
- Signed Python 3.12 for the locked toolchain runtime.
- An explicit Python 3.12 interpreter with PySide6 installed for the Qt WebP oracle.

## Model routing

The project profile uses `gpt-5.6-sol` with `xhigh` reasoning for the primary agent. Bounded delegated work uses `gpt-5.6-terra` with `max` reasoning, and the one-child cap keeps `max_concurrent_threads_per_session` at `1`. If either model name is unavailable for the local account, change it locally after copying the overlay.

The overlay also installs three version-neutral project agents under `.codex/agents/`:

- `pet_researcher` uses `gpt-5.6-luna` with `max` reasoning in read-only mode to inventory source capabilities, recommend v2/v3/v4, and record format confirmation.
- `pet_builder` uses `gpt-5.6-terra` with `max` reasoning and workspace-write access to build only the confirmed package version.
- `pet_reviewer` uses `gpt-5.6-sol` with `xhigh` reasoning in read-only mode to review the selected version independently.

These agents follow the separately installed `crafting-desktop-companion-pets` Skill and its handoff contracts. The overlay intentionally contains no project-local pet Skill; install the global Skill first, then restart or reload Codex after copying the overlay.

The project config contains portable behavior only. Codex trust remains user-global and path-specific: add trust only for the exact local checkout path in the user configuration, never for a parent directory or wildcard, and never add a `[projects]` section to this overlay. Likewise, add only the exact checkout path to Git's global safe-directory list; do not use `safe.directory=*`:

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
