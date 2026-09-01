# Format v2

Use v2 only to repair an existing fixed 8×11 package, or after explicit
confirmation that its fixed grid preserves the required fidelity. Retain a
detected v2 package for a repair; do not migrate merely because a later format
exists.

## Runtime authority at execution

The caller supplies a read-only current runtime repository and, for an
authoritative schema check, its interpreter. Read that repository’s
docs/pet-pack-format-v2.md, schemas/pet-pack-v2.schema.json,
src/shiyi_desktop_pet/pet_registry.py,
src/shiyi_desktop_pet/animation_catalog.py, and
src/shiyi_desktop_pet/autoplay.py. Do not embed a machine-specific repository
path or infer current behavior from a similar pet.

## Package contract

v2 owns spriteVersionNumber 2, a matching lowercase package ID/directory, and
one transparent spritesheet.webp. The atlas is exactly 1536×2288 pixels:
8 columns by 11 rows of 192×208 cells. Every referenced cell must be nonempty;
unused cells remain transparent. New v2 work supplies the fixed action slots
and their required cells, including the two gaze rows. Existing legacy packages
may retain their detected compatible metadata only when the runtime accepts it.

v2 is a fixed compatibility route. It does not acquire dynamic action count,
per-frame timing, forms, layers, or v4 scheduler semantics because a proposal
needs them. If those requirements are real, stop for a confirmed route decision
and read [Format v3](format-v3.md) or [Format v4](format-v4.md).

## Keep acceptance layers separate

- **Schema/package:** validate manifest shape, directory/ID, WebP decode/alpha,
  fixed geometry, referenced cells, and mappings.
- **Registry/Catalog:** verify the supplied runtime’s discovery, admission,
  actions/menu entries, and runtime cross-reference checks.
- **Launched runtime:** when separately authorized, verify the current build,
  scheduler, boundaries, interruption/recovery, and logs.
- **Visual acceptance:** review actual-size acting and readability through
  [Visual QA](visual-qa.md); no package pass grants it.

A valid package remains a local candidate. It does not authorize installation,
integration, publication, or release.
