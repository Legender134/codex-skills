# Canonical Identity and Proportions

Read this after [Identity and Evidence](identity-and-evidence.md) for identity,
likeness, morphology, or proportion work. It owns target-specific measurement,
actual-size review, and the identity gate; it does not choose references.

## Route by morphology

Choose and record one morphology before defining the canonical contract.

| Morphology | Review emphasis |
|---|---|
| `humanoid` | head/body relation, silhouette, clothing mass, hands, knees, feet, and stance anchors |
| `quadruped/animal` | body-to-leg mass, head/ear/tail silhouette, gait anchors, and ground contact |
| `flying` | body/wing or lift silhouette, air anchor, travel envelope, and landing or recovery |
| `object/mechanical` | identifiable body parts, articulation, contact base, and readable operational mass |
| `amorphous/abstract` | recognizable mass, controlled outline change, anchor, and stable readable features |
| `project-defined-custom` | explicitly named target-specific fields, anchors, and review criteria |

Human fields do not apply by default to an animal, object, or abstract pet. All
routes still require target-specific body mass, stable anchors, actual-size
readability, and a visual pass.

## Define target-specific measurements

Each measurement records its target feature, source/reference ID, target range,
tolerance, uncertainty, provenance status, and selection. Measurements are
diagnostics derived from the selected target, never cross-character defaults.

For a humanoid, explicitly account for head height/width, shoulder, torso,
waist, hip, lower garment, feet, negative space between arms/body and legs,
hand/knee/ground anchors, maximum-width region, and clothing mass versus body
mass. Record allowed change by view (front, side, and three-quarter) rather
than forcing a different target into one silhouette.

Measurements diagnose silhouette and drift. They cannot decide beauty,
coordination, age impression, or source likeness. A technical pass never
creates a visual pass.

## Preserve recognition at reduced scale

Preserve high-salience recognition before tertiary texture. Simplify tiny
decoration before shrinking the body or blurring the face. A stylized or chibi
route must preserve target age impression and target-specific proportions.

Use `measure_identity_geometry.py` only to report canvas, alpha bounds, alpha
pixels, centroid, width profile, and maximum-width segment as
`diagnosticOnly`. It must not output a cross-character target, `pass`, or
visual status.

## Build the fixed actual-size board

`make_identity_review_sheet.py` produces a fixed board and sidecar. Preserve
these panels and their hashes: `identity-reference`, `proportion-reference`,
`candidate-original`, `candidate-actual-size`, `light`, `dark`, `checker`,
`silhouette`, and `geometry`.

Review the actual-runtime-size candidate first, then use original pixels and
diagnostics to explain an observed failure. The board must preserve aspect ratio
instead of stretching a source to imitate a target ratio. Light, dark, and
checker panels expose readability, alpha, clipping, and halo problems; they do
not replace a likeness decision.

## Select the canonical identity

The visual artifact workflow is:

```text
generated → technical-candidate → visual-candidate → identity-selected
```

The gate can report `identity-candidate` while evidence is valid but the
canonical file/hash is absent. A canonical candidate needs a readable file and
matching SHA-256, selected reference IDs, technical status `pass`, and an
actual-size visual pass whose reviewed artifact hash matches the canonical hash.
Only a `user` or `independent` reviewer can supply that visual pass. A
technical verdict that claims visual acceptance remains a blocker
(`TECHNICAL_CANNOT_GRANT_VISUAL_PASS`).

Store the canonical path/hash and gate evidence in the
[Identity contract](../templates/identity-contract.json). A changed canonical
hash invalidates dependent visual claims; read [Generation Job
Graph](generation-job-graph.md) for the deterministic descendant handling.

## Stop conditions

Do not select a canonical identity when high-salience target evidence is
missing, its uncertainty is unapproved, the actual-size review fails, or the
required independent/user verdict is unavailable. For local anatomy or frame
defects after selection, read [Repair and
Convergence](repair-and-convergence.md) rather than reopening the identity gate
without a causal reason.
