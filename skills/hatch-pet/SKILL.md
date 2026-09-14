---
name: hatch-pet
description: Create, repair, validate, and package Codex v2 animated pets with an 8x11 atlas and 16 look directions. Use for Codex pet artwork and spritesheet workflows; DesktopCompanion v2/v3/v4 pets use crafting-desktop-companion-pets.
---

# Hatch Pet

## Overview

Create a Codex-compatible v2 animated pet from a concept, brand cue, company/prospect name, one or more reference images, or any combination of those inputs. Every newly hatched pet is an 8x11 atlas with the 9 standard animation rows plus 16 clockwise look directions and is packaged with `spriteVersionNumber: 2`. The intermediate 8x9 atlas exists only to assemble and review rows 0-8; never package it as a new pet.

User-facing inputs are optional. If the user omits a pet name, infer one from the concept, brand, company, or reference filenames; if that is not possible, choose a short friendly name. If the user omits a description, infer one from the concept or references. If the user omits reference images, generate the base pet from text first, then use that base as the canonical reference for every animation row.

## Existing Inputs And Upgrades

Treat character art, generated images, standard or v2 atlases, contact sheets, and built-in pet art as first-class grounding inputs.

- Preserve user-provided art as a generation reference; do not assume it already has final cell geometry.
- For an existing valid 8x9 atlas, use it as the rows `0-8` intermediate after deterministic and visual validation, then generate rows `9-10` and package the result as v2.
- For an existing 8x11 atlas, preserve approved standard rows. If a look cell fails, correct the complete containing 8-frame row before deterministic reassembly. Never package a newly generated one-off repair cell beside cells from another generation.
- For a built-in pet, extract and use its atlas or neutral/idle cell as the canonical identity reference.
- Include every image that defines head shape, face, palette, markings, material, flame/ears/hair, props, or look mechanics in look-direction generation.
- When a renderer or source provides a dedicated neutral/front frame, pass it through `--neutral-cell`; otherwise use the approved idle/default frame. The 16 directional cells never treat `000` as neutral.

## Generation Delegation

Use `$imagegen` for all normal visual generation.

Before generating base art, row strips, or repair rows, load and follow the installed image generation skill:

```text
${CODEX_HOME:-$HOME/.codex}/skills/.system/imagegen/SKILL.md
```

Do not call the Image API, image CLI, or any other image-generation path directly. Let `$imagegen` choose its own built-in-first path and fallback rules. If `$imagegen` says a fallback requires confirmation, ask the user before continuing.

When invoking `$imagegen`, pass the generated pet prompt as the authoritative visual spec. Pet prompts should stay concise, state-specific, sprite-production oriented, and grounded in the listed input images. Keep longer policy and QA rules in this skill and the deterministic review scripts rather than expanding them into every image prompt. Do not wrap prompts in the generic `$imagegen` shared prompt schema.

Use this skill's scripts for deterministic image work only: preparing layout guides and prompts, mirroring approved `running-left`, extracting frames, validating rows, composing the final atlas, and creating contact-sheet plus motion-preview QA media. Parent-owned shell/`jq` steps handle manifest updates, packaging, and cleanup.

## Runtime Dependencies

On the Windows desktop, use `load_workspace_dependencies` when available and set `PYTHON` to its returned native Python executable. In WSL or a standalone CLI, use an explicitly configured `HATCH_PET_PYTHON`, or the existing Linux runtime at `$HOME/.local/share/codex-skill-runtimes/hatch-pet/bin/python`. Verify that the executable exists and `"$PYTHON" -c "import PIL; print(PIL.__version__)"` succeeds before running scripts. Do not use a Windows interpreter path from Linux or assume an arbitrary `python` has Pillow.

The WSL runtime supports the deterministic Python scripts. Fresh visual generation still requires an available image-generation tool; if that tool is unavailable, continue authorized validation or packaging of existing assets and report the missing capability. Do not silently switch to API-key billing.

The command examples use Bash and `jq`. When `jq` is unavailable, use the verified Python interpreter for the same JSON operations; on Windows translate shell orchestration to PowerShell or Python while preserving arguments and outputs. `SKILL_DIR` is this skill's root directory, including when reading a reference file.

## Storage Controls

The built-in `$imagegen` path stores generated PNG bytes in the rollout that invokes it, even when it also writes a file under `${CODEX_HOME:-$HOME/.codex}/generated_images`. Deleting files later reduces filesystem use, but it does not shrink an already-written rollout. Keep image generation isolated and bounded:

- For substantial generation runs where delegation is available and useful, isolate one visual job per worker. Small repairs and deterministic checks can stay with the primary agent.
- Workers must return only `selected_source=...` and `qa_note=...`; they must not include Markdown image previews, base64, or extra visual attachments in their final response.
- Keep parent vision input focused on final QA and decision-critical originals. Inspect a source image when conflicting evidence or a repair requires it.
- Preserve generated originals after copying into `decoded/`. At closeout list exact cleanup candidates; remove an original or directory only within existing explicit authorization for those targets.
- For storage-sensitive full runs, ask the user whether to use the `$imagegen` CLI fallback when available. That path requires local API credentials and explicit user confirmation, but it can avoid built-in image payloads being embedded in rollout events.

## Select the relevant workflow

- For a new pet or standard-row generation, read [generation-workflow.md](references/generation-workflow.md). Brand discovery can stay with the primary; existing references usually need no separate research task.
- For look-row creation, repair, or direction acceptance, read [look-direction-workflow.md](references/look-direction-workflow.md). Preserve cardinal grounding, coherent rows, registration, and independent blind direction evidence. Three blind verdicts require isolated inputs, not three concurrent agents.
- Read [worker-prompts.md](references/worker-prompts.md) only when delegating a visual or review job. Select a role from the current tool contract; never copy an unavailable model name.
- For an existing-pet repair or final delivery, read [repair-and-acceptance.md](references/repair-and-acceptance.md). Start at the affected stage, preserve approved rows, and rerun checks invalidated by that change. Do not restart a full hatch for a narrow deterministic correction.

Do not read every reference for a metadata-only question. New pets still require all nine standard rows, 16 directions, deterministic and visual QA, and `spriteVersionNumber: 2`. A missing generation tool must be reported as a capability gap, not worked around by an unapproved paid API path.
