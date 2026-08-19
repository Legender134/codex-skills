---
name: crafting-desktop-companion-pets
description: Use when creating, repairing, reviewing, validating, or packaging a pet for this user's DesktopCompanion software, including its v2 fixed-atlas packs, v3 single-form packs, or v4 layered and multiform packs; not for generic Codex animated pets.
---

# Crafting DesktopCompanion Pets

Research the character first, recommend the format that best preserves the requested source fidelity, and obtain user confirmation before locking the package version. After confirmation, build the smallest valid DesktopCompanion package that preserves that agreed fidelity. Runtime correctness and visual acceptance are separate gates; neither substitutes for the other.

## Research and confirm before producing assets

1. For an existing package, identify the exact target directory, its declared format, manifest-to-asset mappings, approved assets, and unrelated dirty work. Inspect only that evidence and references explicitly named by the target; never borrow values from neighboring experiments. Preserve the detected format for repair; if source research reveals that faithful restoration requires migration, recommend the migration and obtain user confirmation before changing versions.
2. For a new package: Research source material before recommending a format. Do not rely on the user's memory alone: inventory observed and plausible forms, transformations, actions, gaze, layered or wide effects, quality variants, sequences, restoration needs, and autoplay relationships that could affect the format choice.
3. Treat research as sufficient for a recommendation only when distinctive source behaviors likely to affect the version are covered, observations are separated from uncertainty, and any remaining uncertainty that could change the route is stated. Continue accessible research when it can resolve such uncertainty; otherwise compare the affected routes explicitly.
4. Present a recommendation that names the preferred version, the source evidence and runtime features supporting it, the fidelity each viable route preserves or omits, production complexity, future extensibility, and unresolved uncertainty. Prioritize faithful restoration of the source over convenience, then recommend the least complex version that preserves that fidelity.
5. Present the format recommendation and obtain user confirmation before locking v2, v3, or v4. An initial version preference is evidence, not confirmation. For a new package, only an explicit user choice made after the research-backed recommendation satisfies `FORMAT_CONFIRMATION`; time pressure or a request to skip questions does not waive this gate. Before confirmation, research and evidence boards may proceed, but do not lock the manifest schema, final action/form contract, atlas architecture, or begin batch asset production.
6. After confirmation, route by required runtime features, never by action count:

| Route | Select when |
|---|---|
| v2 | Repairing an existing fixed 8 × 11, 192 × 208 atlas pack that does not require migration. |
| v3 | Creating an ordinary new single-form pet with one atlas and dynamic actions. This is the default for new single-form pets. |
| v4 | Any required layered atlas, wide effect, full/simplified rendering, multiple form, transformation, sequence, safe restoration, or bucket/shared-cooldown autoplay exists. |

7. Read [research-and-identity.md](references/research-and-identity.md) while collecting source evidence and preparing a new-package or migration recommendation. Read [format-and-runtime.md](references/format-and-runtime.md) and the detected version's format document before repairing an existing package. For a new package or migration, read the confirmed version's format document after confirmation. Read [visual-production-and-qa.md](references/visual-production-and-qa.md) while making or reviewing visual assets. Read [handoff-contracts.md](references/handoff-contracts.md) when recording or handing off work.

Do not migrate an existing v2 or v3 package merely for convenience. Do not turn a v3 request into v4 only because it has many actions.

## Universal gates

### Value contract

Record every decision in the action/form contract with exactly one provenance status and a separate `selection`:

| Status | Meaning |
|---|---|
| `REQUIRED` | A user or runtime constraint that must be satisfied. |
| `DERIVED` | Geometry or another value computed from recorded inputs. Record its inputs and calculation. |
| `PROPOSED` | An agent-originated value lacking recorded user or governing-artifact approval. |
| `APPROVED` | A value approved in a recorded user instruction or governing artifact. Cite it. |

| `selection` | Meaning |
|---|---|
| `candidate` | The value is not yet chosen. |
| `selected` | The value passed applicable self-review and may be used in an authorized completed package. |

Statuses record provenance and evidence, not package eligibility; `selection` records adoption. Do not present a `candidate` as selected or a `PROPOSED` value as `APPROVED`. In an authorized autonomous creation request, a self-reviewed `PROPOSED` choice with `selection: selected` may be used in the completed package while remaining `PROPOSED`; it does not require user approval unless the request explicitly requires it or unresolved subjective ambiguity blocks safe selection.

### Build and review loop

1. After a new package or migration version is confirmed, or after an existing package's detected version is retained for repair, establish the final evidence ledger, identity master, and action/form contract before batch production. For a repair that retains the detected package version, `FORMAT_CONFIRMATION` is not required. For an authorized creation request, an agent-self-reviewed `PROPOSED` master with `selection: selected` that passes applicable identity and visual gates may proceed without further user approval; use `APPROVED` only for recorded user or governing-artifact approval. The format confirmation is a distinct mandatory gate for new packages and migrations, not a requirement to request approval for every creative or timing choice.
2. Make key poses and anchors before intermediate frames. Interpolate only structurally stable adjacent poses.
3. Validate the selected manifest, assets, and actual Registry-to-Catalog/runtime route. Resolve operational paths from the actual source/build or launched version being validated. For current repository HEAD, the log is `%LOCALAPPDATA%\DesktopCompanion\logs\DesktopCompanion.log`. When documentation disagrees with executable source or build behavior, record the conflict and inspect the path used by the launched version.
4. Self-review every applicable visual and runtime gate. Repair the smallest failing master, action, interval, layer, configuration, or test; rerun affected gates.
5. Stop only when all applicable gates pass. Ask for user visual approval only when the current request requires it or a subjective ambiguity cannot be resolved safely.

## Scope and authority

Creating or repairing assets authorizes only the scoped package work. It does not authorize built-in integration, live installation, commits, pushes, publication, release builds, downloads, browser/account actions, or global configuration. Obtain explicit authority before any of those operations.

Stop and report the exact blocker when target identity, approved source inputs, write scope, or a required runtime/visual gate cannot be established safely.
