# Format v4

Use v4 only when the confirmed fidelity need requires multi-atlas layers, a
large effect beyond the body, forms, transformations, sequences, restoration,
or bucket/shared-cooldown behavior. It is not a version-number upgrade for a
single-atlas pet that v3 can represent.

## Runtime authority at execution

The caller supplies a read-only current runtime repository and, for an
authoritative schema check, its interpreter. Read that repository’s
docs/pet-pack-format-v4.md, schemas/pet-pack-v4.schema.json,
src/shiyi_desktop_pet/pet_registry.py,
src/shiyi_desktop_pet/animation_catalog.py,
src/shiyi_desktop_pet/autoplay.py, and
src/shiyi_desktop_pet/multiform.py. Do not bake any user path into this skill or
treat old documentation as authority over the supplied executable route.

## Package contract

v4 owns its case-sensitive camelCase package ID and keys, one to eight
transparent atlases, atlas-specific cell geometry, and composited action layers.
Each action has exactly one hit-test body layer; effects may expand the rendered
window without changing the body’s world anchor, hit test, or desktop position.
Validate every action under full and simplified quality so no rendered frame is
empty and the body remains readable.

Each form has idle and left/right move coverage. Gaze belongs only to the
default form. A non-default form needs a transformation exit. Transformations
define enter, resident, and exit behavior; sequences define finite steps,
repeat/hold, optional form changes, and explicit safe-stop boundaries.
Restoration and hard cleanup must return safely to the default form and clear
pending long-event state.

Only v4 transformations or sequences with their own autoplay records enter
bucket scheduling. Buckets have their own deadlines; a started event updates
declared shared cooldown groups. Action menu/autoplay fields and bucket
scheduler fields are separate controls.

## Keep acceptance layers separate

- **Schema/package:** validate atlas/layer geometry, frame maps, body hit-test
  layer, full/simplified visibility, forms, transformations, sequences,
  restoration, buckets, and cooldown-group references.
- **Registry/Catalog:** verify the supplied runtime’s package discovery,
  cross-reference checks, actions/menu paths, and form admission.
- **Launched runtime:** when separately authorized, verify composition anchors,
  forms, pending/restore/cleanup, bucket deadlines, shared cooldowns,
  interruption, boundaries, and logs.
- **Visual acceptance:** use [Visual QA](visual-qa.md) to decide body
  occupancy, action readability, and effects at actual size; the layered
  package check cannot decide them.

A validated v4 package remains a local candidate and grants no installation,
integration, publication, or release authority.
