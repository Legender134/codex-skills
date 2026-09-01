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

## Apply the aesthetic coherence gate

Judge beauty as target-specific visual coherence, not a generic attractiveness
score and not a task delegated to the user. Compare the selected identity and
proportion evidence, candidate original, actual-runtime-size candidate, and
silhouette. Record observations for:

- source likeness, age/character impression, expression, and intentional style;
- head/body relation, shoulder–torso–waist–hip flow, limb length, clothing mass,
  and where the silhouette carries its maximum width;
- balanced positive/negative space, readable separation of arms/body and legs,
  stable stance/grounding, and a deliberate visual center;
- hierarchy of face, costume blocks, props, color, and detail at desktop size;
  and
- pose appeal and, when applicable, motion arcs, rhythm, shape continuity, and
  controlled hair/garment response.

Reject a candidate that visibly reads as unintended oversized-head, childlike,
short/stout, swollen, top-heavy, pinched, weakly grounded, or whose wide garment
hides an unresolved body. Adapt these symptoms to the selected morphology; the
target evidence, not another pet or a generic beauty template, governs the
desired result. A named internal aesthetic concern cannot pass because metrics
are within tolerance, downstream work exists, or the user could identify it.

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
actual-size builder self-review followed by an independent visual pass; both
reviewed artifact hashes must match the canonical hash. Supply verdicts in
review order and retain both accepted verdict IDs. A later user verdict records
acceptance or a genuinely irreducible subjective choice; it cannot replace or
precede internal review. A technical verdict that claims visual acceptance
remains a blocker
(`TECHNICAL_CANNOT_GRANT_VISUAL_PASS`).

Store the canonical path/hash and gate evidence in the
[Identity contract](../templates/identity-contract.json). A changed canonical
hash invalidates dependent visual claims; read [Generation Job
Graph](generation-job-graph.md) for the deterministic descendant handling.

## Stop conditions

Do not select a canonical identity when high-salience target evidence is
missing, its uncertainty is unapproved, the actual-size review fails, or the
required builder self-review or independent internal review is unavailable. For
local anatomy or frame defects after selection, read [Repair and
Convergence](repair-and-convergence.md) rather than reopening the identity gate
without a causal reason.
