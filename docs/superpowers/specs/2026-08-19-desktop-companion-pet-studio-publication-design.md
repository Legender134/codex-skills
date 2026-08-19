# DesktopCompanion Pet Studio Publication Design

## Status and decision

Publish the already validated DesktopCompanion pet-production workflow as two installable layers in `Legender134/codex-skills`:

1. an ordinary Codex Skill at `skills/crafting-desktop-companion-pets`; and
2. a copyable project overlay at `templates/desktop-companion-pet-studio` containing the project model-routing configuration and the reproducible Windows media toolchain.

This keeps the Skill independently installable while preserving the toolchain's tested relative paths. It avoids a new plugin abstraction and does not require binaries, models, credentials, or machine-specific trust paths in Git.

## Baselines and provenance

- Target repository baseline: `Legender134/codex-skills` `main@9d2782ca05cb0e6dee6ec6b4ab807f94411c243f`.
- Media-toolchain source: reviewed DesktopCompanion branch commit `9405019e74ffee1cfa563032b2ed56b1d6ded903`.
- Skill source: the installed `crafting-desktop-companion-pets` Skill containing `SKILL.md`, `agents/openai.yaml`, and four routed references.
- Existing target-repository content under `skills/codex-sync-skills`, `skills/repository-aligned-development`, and `agents/repository-aligned-development` remains unchanged except for root documentation links.

The target branch is `feature/desktop-companion-pet-studio`; delivery is a pull request to `main`, not a direct push to `main`.

## Goals

- Let another Codex user install the pet-production Skill from the public repository.
- Let a DesktopCompanion contributor copy one directory overlay into a compatible source checkout and obtain the same model-routing profile, hash-locked dependencies, setup script, independent verifier, and operator documentation.
- Preserve the v2/v3/v4 decision gate: research source material first, recommend the least complex format that preserves fidelity, then obtain post-research user confirmation before locking a new package version.
- Make the large local toolchain reproducible from source URLs, versions, sizes, SHA-256 hashes, extracted-file inventories, Python requirement hashes, and publisher checks.
- Keep setup local to `%LOCALAPPDATA%\DesktopCompanionDev\pet-toolchain` and keep product installs, project virtual environments, PATH, and registry state outside its mutation scope.

## Non-goals

- Do not publish character art, anime captures, pet packages, browser state, cookies, account data, model weights, executable archives, wheel caches, installed virtual environments, QA transcripts, or local failure roots.
- Do not publish the user's real Codex trust entries, Git safe-directory values, usernames, home paths, worktree paths, or tokens.
- Do not make the Skill choose v4 merely because a character has many actions.
- Do not build a Codex plugin, marketplace package, GUI installer, release executable, or automatic repository copier in this change.
- Do not rerun a second 1.4 GB production installation merely to prove that an unchanged, relocated source overlay works; use the complete contract suite and the existing reviewed end-to-end installation evidence.

## Repository layout

```text
codex-skills/
|-- README.md
|-- skills/
|   `-- crafting-desktop-companion-pets/
|       |-- SKILL.md
|       |-- agents/openai.yaml
|       `-- references/
|           |-- format-and-runtime.md
|           |-- handoff-contracts.md
|           |-- research-and-identity.md
|           `-- visual-production-and-qa.md
`-- templates/
    `-- desktop-companion-pet-studio/
        |-- README.md
        |-- .codex/config.toml
        |-- docs/development-pet-toolchain.md
        |-- requirements/pet-media.in
        |-- requirements/pet-media.txt
        |-- scripts/pet_toolchain_common.ps1
        |-- scripts/setup_pet_toolchain.ps1
        |-- scripts/verify_pet_toolchain.ps1
        |-- tests/test_pet_toolchain_contract.py
        `-- tools/
            |-- pet-toolchain.lock.json
            |-- verify_pet_media.py
            `-- verify_qt_webp.py
```

The template directory is an overlay root: its contents are copied into the root of a compatible DesktopCompanion checkout. This preserves all existing `../requirements`, `../tools`, and repository-root safety relationships without changing production scripts.

## Skill behavior

The Skill remains a normal implicitly discoverable Codex Skill. It owns judgment and workflow, not media binaries:

- research and evidence sufficiency;
- identity and proportion selection;
- v2/v3/v4 recommendation and confirmation;
- action/form contracts and provenance;
- visual production and self-review;
- runtime validation and handoff reports.

The Skill references format documents in the target DesktopCompanion checkout. It must therefore state that it applies to this user's DesktopCompanion formats rather than generic Codex animated pets. No tool download or remote mutation is implied by invoking the Skill.

## Project model-routing profile

The template `.codex/config.toml` contains only portable project behavior:

- `gpt-5.6-sol` with `xhigh` reasoning for the primary agent;
- one active child at a time;
- `gpt-5.6-terra` with `max` reasoning for bounded delegated work;
- interrupt-message support.

The template README must explain that these model names require account availability and may be replaced locally. Trust entries remain user-global and path-specific, so they are documented as placeholder examples and never included in the project config. The existing optional global repository-alignment guidance in this repository is referenced rather than duplicated.

## Reproducible media toolchain

The overlay carries source and metadata only. Setup reconstructs the toolchain on Windows x64 from:

- exact FFmpeg, ImageMagick, libwebp, and extractor assets;
- exact `isnet-anime` and `u2net_human_seg` ONNX model assets;
- a fully hash-pinned Python 3.12 requirements lock;
- complete extracted-file inventories and entrypoint/version/publisher policies.

Setup stages into a private directory, verifies before and after the immutable version move, and publishes `current.json` only after both gates pass. The independent verifier rechecks the published manifest, inventories, model hashes, Python runtime/tree, tool versions, real media smoke, animated WebP timing/alpha, and Qt/Pillow agreement.

Operator examples use placeholders such as `C:\path\to\PySide6\python.exe`. The public template contains no real username, machine path, browser path, or trust target.

## Installation and data flow

1. Install `skills/crafting-desktop-companion-pets` with `skill-installer` or copy it into the user's Skill directory.
2. Copy the contents of `templates/desktop-companion-pet-studio` into a compatible DesktopCompanion checkout.
3. Review `.codex/config.toml` and adjust model names only when the account lacks the documented models.
4. Add exact local Codex trust and Git safe-directory entries manually; never use a parent directory or wildcard.
5. Run `scripts/setup_pet_toolchain.ps1` with an explicit PySide6-capable Python 3.12 interpreter.
6. Require setup's success marker, then run `scripts/verify_pet_toolchain.ps1` and require `PET TOOLCHAIN VERIFIED`.
7. Use the Skill for research, version recommendation, asset production, visual QA, and package/runtime acceptance.

Downloaded assets and installed files remain under the machine-local ToolRoot and never enter the checkout.

## Portability and safety boundaries

- Supported installation target: Windows x64 with PowerShell 7, signed Python 3.12, and an explicit PySide6-capable Python 3.12 interpreter for the Qt oracle.
- Setup may download only lock-declared HTTPS assets. The verifier does not download or repair state.
- Archive traversal, links, reparse points, protected-root overlap, unexpected inventory content, hash mismatch, version mismatch, and publisher mismatch fail closed.
- Python and pip stages use absolute validated executables, isolated flags, a clean environment, and hash-required binary wheels.
- Verification cleanup binds workspace, media, and Numba-cache identities through anchored no-follow handles before deletion. The documented same-Windows-user pre-bind ordinary-object boundary remains explicit.
- Model and executable licenses remain with their upstream projects. The repository publishes URLs and verification metadata, not redistributed binaries or weights.

## Documentation

The root README adds the new Skill and template to the existing catalog and gives a short two-layer installation summary. The template README provides:

- prerequisites;
- overlay-copy instructions;
- model-routing explanation;
- exact setup and verify commands with generic paths;
- trust and safe-directory guidance;
- expected markers;
- download-size and installation-size expectations;
- links to the detailed operator guide.

The detailed operator guide is copied from the reviewed source and sanitized so every machine path is generic while the command contracts remain testable.

## Verification strategy

The publication candidate must pass all of the following before push:

1. Target-repository baseline WSL suite: 26 existing synchronization tests.
2. `quick_validate.py` for all three published Skills, including the new pet Skill.
3. The relocated media-toolchain contract suite: 172 tests using the existing validated Python 3.12 development environment.
4. PowerShell parser checks for all three toolchain scripts.
5. Python compilation for the two verifier helpers and the contract test.
6. Strict UTF-8 and replacement-character checks for all added text files.
7. JSON parsing and lock schema/inventory checks.
8. Link checks for Skill references and template documentation.
9. Secret, credential, username, absolute-machine-path, binary-extension, model-weight, archive, and unusually-large-file scans.
10. `git diff --check` plus name-status, stat, and full-diff review from `9d2782ca` through the exact submission candidate.

Skill content is copied without changing its behavioral rules. Validation therefore checks Skill structure, routed references, and realistic routing/decision scenarios; it does not invent a second competing Skill implementation.

## Submission policy

Only the following coherent deliverables enter the pull request:

- the new Skill directory;
- the new project-overlay template;
- root README catalog/install changes;
- this approved design and its implementation plan when they remain useful to maintainers.

Local prototypes, generated reports, copied caches, model assets, binaries, diagnostic evidence, and source-worktree history are excluded. Immediately before push, compare the exact branch diff to `9d2782ca`, confirm the worktree is clean, and push only `feature/desktop-companion-pet-studio`. Create a pull request targeting `main` and do not merge it automatically.

## Acceptance criteria

- A fresh reader can identify and install the Skill independently.
- A compatible DesktopCompanion checkout can receive the overlay without editing production relative paths.
- Documentation contains no real local path or secret and explains required local trust separately.
- The template contains no binary, model, wheel, cache, or QA artifact.
- All verification gates above pass with fresh exit-zero evidence.
- The remote change exists as a reviewable pull request against `main`, with no unrelated changes.
