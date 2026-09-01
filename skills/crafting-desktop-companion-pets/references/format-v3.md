# Format v3

Use v3 for a single-form pet that needs one dynamic transparent atlas,
character-specific actions, or per-action timing without v4 layers, forms, or
complex long-event behavior. Retain an existing v3 package for a repair unless a
confirmed fidelity need changes the route.

## Runtime authority at execution

The caller supplies a read-only current runtime repository and, for an
authoritative schema check, its interpreter. Read that repository’s
docs/pet-pack-format-v3.md, schemas/pet-pack-v3.schema.json,
src/shiyi_desktop_pet/pet_registry.py,
src/shiyi_desktop_pet/animation_catalog.py, and
src/shiyi_desktop_pet/autoplay.py. Do not use a hard-coded local path or assume
that another v3 pet proves this package’s runtime behavior.

## Package contract

v3 owns a matching package ID/directory and one transparent spritesheet.webp.
Each cell is 192×208; atlas width and height are dynamic positive multiples of
those dimensions rather than a fixed 8×11 grid. It requires exactly one looping
idle, ordinary left and right movement, and at least one interaction. Actions
have character-specific IDs, mappings, frame counts, and either a shared frame
duration or per-frame durations; no fixed action quota is implied.

Use mirroring only when the source and mirrored directions are compatible with
the character’s asymmetry. Burst movement records its travel frames, direction,
distance/boundary behavior, and cooldown rather than imitating travel by
sliding a standing frame. The optional v3 state route owns finite enter,
resident, and exit actions; it is not a substitute for v4 forms or sequences.

## Keep acceptance layers separate

- **Schema/package:** validate dynamic atlas cells, action mappings/timing,
  nonempty references, and v3-specific state or mirror relationships.
- **Registry/Catalog:** verify the supplied runtime’s role, menu, autoplay,
  state, and cross-reference admission.
- **Launched runtime:** when separately authorized, verify true scheduling,
  movement edges, interruption/recovery, and logs in the selected build.
- **Visual acceptance:** use [Visual QA](visual-qa.md) for actual-size motion,
  lifecycles, and body readability; technical success remains nonvisual.

A schema-valid v3 package is not installed, integrated, published, or released
by validation alone. For layered effects, forms, transformations, sequences, or
bucket/shared-cooldown semantics, read [Format v4](format-v4.md).
