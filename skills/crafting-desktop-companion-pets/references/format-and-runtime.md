# Format and Runtime

Read the selected current repository format document before changing a package: `docs/pet-pack-format-v2.md`, `docs/pet-pack-format-v3.md`, or `docs/pet-pack-format-v4.md`. Treat its schema as shape validation, not runtime acceptance.

## Format recommendation gate

For a new pet, use the source capability inventory from [research-and-identity.md](research-and-identity.md) to compare viable formats before selecting one. The recommendation must state source evidence, fidelity preserved or omitted, runtime capability fit, production complexity, extensibility, and uncertainty. Prefer faithful restoration, then the least complex version that preserves the agreed fidelity. Obtain explicit user confirmation of v2, v3, or v4 before locking the schema, final contracts, atlas architecture, or batch production.

For a new package, an initial version preference is evidence, not confirmation. Record `FORMAT_CONFIRMATION` only from an explicit user choice made after the research-backed recommendation. Time pressure or a request to skip questions does not waive this gate. If unresolved source uncertainty could change the version, continue accessible research or show the affected alternatives rather than silently choosing the more complex route.

For an existing package, its discovered version governs repair. Read the detected version's format document before repairing an existing package. Retaining that version does not require `FORMAT_CONFIRMATION`; changing it is a migration and requires a research-backed recommendation plus post-research user confirmation.

## Candidate formats and isolation

| Package state or required feature | Format | First checks |
|---|---|---|
| Existing fixed 8 × 11 pack | v2 | Confirm the target manifest, 1536 × 2288 transparent WebP, fixed rows, and whether migration is actually required. |
| New ordinary single form and one atlas | v3 | Confirm dynamic actions, required capabilities, and a transparent `spritesheet.webp`. |
| Existing single-form dynamic pack | v3 | Preserve its mapping unless a required feature needs a deliberate migration. |
| Layers, wide effects, full/simplified quality, forms, transformations, sequences, safe stop/restore, or bucket/shared cooldown | v4 | Confirm atlas/layer/form/action mappings and the entire v4 contract before edits. |

This table supports the post-research recommendation; it is not permission to lock a new pet's version before the confirmation gate.

For repair, record the target directory; selected manifest; format; manifest-to-atlas/action/layer mappings; approved assets; and immutable comparison set. Preserve unrelated dirty work. A nearby package, ignored file, fixture, or experiment is not evidence unless the target explicitly references it.

## High-value format invariants

| Version | Invariants to verify |
|---|---|
| v2 | Directory ID match; `spriteVersionNumber: 2`; `spritesheet.webp`; transparent 1536 × 2288 WebP; 8 × 11 grid of 192 × 208 cells; fixed action slots and required non-empty/transparent cells. |
| v3 | Directory ID match; one transparent `spritesheet.webp`; 192 × 208 cells; atlas dimensions are cell multiples; exactly one looping idle, left and right `move`, and an `interaction`; mapping references valid non-empty cells; mirror only when visual asymmetry permits. |
| v4 | Exact case-sensitive ID/directory match and camelCase technical keys; 1–8 transparent WebP atlases with valid cells; each action has exactly one body/hit-test layer; maintain anchor equations; validate every action frame in full and simplified quality; each form has idle and both moves; only default form may gaze; non-default forms need a transformation exit. |

For v4, also validate transformation enter/resident/exit progression; sequence repeat, hold, `formAfter`, `safeStopAfter`, pending, restore, and idempotent cleanup; and bucket candidate weights, shared cooldown accounting, manual-versus-automatic starts, and deferred unavailable deadlines. Do not use v3 `states` or `spritesheetPath` in v4.

## Runtime validation

1. Validate the selected version's schema against the target manifest.
2. Run selected-version tests that cover parsing, atlas decoding, cross-references, Registry, and Catalog. Do not run v4-only checks for an undiscovered or v2/v3 target.
3. Re-scan the target package in the app when authorized; exercise applicable actions, forms, full/simplified rendering, and restoration behavior.
4. Resolve operational paths from the actual source/build or launched version being validated. For current repository HEAD, the log is `%LOCALAPPDATA%\DesktopCompanion\logs\DesktopCompanion.log`. When documentation disagrees with executable source or build behavior, record the conflict and inspect the path used by the launched version for that package's isolated errors. A failed package must not be treated as accepted because other packages load.

Schema validation alone does not prove directory identity, WebP decode/alpha, cell availability, cross references, Registry admission, Catalog behavior, or in-app runtime behavior.
