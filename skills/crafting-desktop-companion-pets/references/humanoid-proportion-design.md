# Humanoid Proportion Design

Use for humanoid creation or proportion repair, including flying humanoids.
For animals, objects and abstract pets, use their own morphology contract.
This reference supplies design decisions; the canonical identity gate still
owns selection, evidence authority and visual acceptance.

## Choose the design route

A desktop pet is an interactive character at a chosen display size. Small
on-screen size does not require a large head. Retain the selected source/design
proportions unless the brief calls for adaptation. Reuse the user's existing
style choice; ask only when an unresolved choice would change the requested
design. Render quality, body proportions and v2/v3/v4 format are separate.
Q art can be high quality, and a modeled look does not require a 3D runtime.

| Route | Proportion standard | Failures to correct |
|---|---|---|
| Q / chibi | Design the head, face, neck, torso, limbs, hands/feet and costume as one simplified character. Choose torso-to-leg balance for the intended personality; retain recognizable face/hair/costume cues and readable action shapes. | Enlarging an otherwise unchanged head; detailed adult face on an incoherent miniature body; hair swallowing the torso; hands, feet or gestures disappearing at the intended size. Intentional short limbs or a large head are not failures by themselves. |
| High-quality modeled style / source proportions | Preserve the target's age, build and head–neck–shoulder–ribcage–pelvis–limb relationships, with coherent volume across views and poses. For an adult source, retain its adult body design; for a child, stocky or exaggerated source, retain that design instead. | Automatically making every character slender or adult; enlarging the head to solve a scale problem; pinched shoulders, disconnected torso/pelvis, implausible limb connections, or a long skirt used to conceal unresolved legs. |

Head counts are sketch references, not acceptance bands. Common Q studies use
roughly 2–4 heads; adult figure studies often compare about 7.5-head natural
and 8-head idealized constructions. Use such studies only when compatible with
the brief, label them `PROPOSED`, and derive the selected target from its own
evidence/design. Do not convert these ranges into universal defaults, forced
thresholds, or automatic visual passes. Do not average the two routes into an
unrequested large-head adult hybrid. A preference for one character's candidate
does not select proportions for other characters or reject the whole Q route.

## Make the body relationships explicit

Use [Design and Repair Examples](design-and-repair-examples.md) when a verbal
proportion choice is not yet an executable drawing instruction. Its construction
diagram explains landmarks, not a required body template or approved character.

In the existing brief/identity contract, record the route, its authority,
reference IDs and permitted stylization. Describe the relationships that must
survive generation: head versus shoulders, neck connection, torso versus legs,
ribcage/waist/pelvis flow, limb thickness and length, hand/foot size, and hair and
garment volume around the body. Use only meaningful target-specific measures.
Keep requested values separate from observed values and uncertainty.

For a head-count diagnostic, define one head as scalp crown to chin, excluding
hair, hats and ornaments. Compare crown-to-sole stature in a suitable neutral
view; record footwear offsets, camera/view and pose. Measure hair mass separately
because it can make the figure look top-heavy even when the anatomical head is
small. Alpha bounds and skirt hems are not anatomical stature or leg length.
An occluded crown, pelvis, knee or foot, or a strongly foreshortened pose, makes
the corresponding measurement uncertain; do not fabricate precise ratios.

Use a simple clothed construction sketch, mannequin/blockout, or sufficiently
clear source views to explain the underlying body. Long garments may cover the
legs, but hip, knee and foot locations must still explain stance and bending.
Distinguish observed anatomy from proposed reconstruction. This is a structural
aid, not a request for a new costume or an uncovered character.

Before batch animation, check a neutral view, a side/three-quarter view that
resolves depth, and a representative action pose that stresses the proportions
(such as bending, reaching or the character's own locomotion). Reuse adequate
existing evidence or key poses; do not regenerate a full turnaround by habit.
Check stable body volume, plausible joint connections and readable gestures,
not equal projected pixel lengths in different poses.

## Separate proportions from desktop presentation

Record source/export resolution, character frame geometry, composed-frame
geometry when layers differ, intended display scale, and observed DPI if tested.
Do not equate a character layer with the complete runtime window or a browser
video's pixels with a product's default pet size. Use the target runtime and
manifest as authority; no historical canvas dimension applies to every pet.

Review the intended display size first, then diagnose with the source image.
When scale is uncertain, compare the same candidate at supported display sizes
without altering anatomy. For a runtime-scaling simulation, derive all sizes
from the same exported base frame; a fresh high-resolution render at each size
answers a different question. Label static simulations and actual runtime
captures separately. Enlarging a low-resolution frame cannot restore lost detail.

| Observed problem | First causal repair |
|---|---|
| Source looks coherent, whole character is too small on the desktop | Inspect excessive transparent margins, body occupancy, framing and supported display scale. Preserve aspect ratio and intentional movement/effect space. |
| Source is clear but exported or enlarged frame is soft | Check export resolution, resampling and available pixel detail; improve the authorized asset pipeline, not the head size. |
| Size is sufficient but face or gesture merges with nearby detail | Simplify tertiary texture, separate major shapes/value groups, or revise the key pose while retaining identity cues. |
| The canonical candidate itself has incorrect head/body, shoulder/torso or limb relationships at source size | Redesign its structure using target evidence, then recheck affected poses and claims. Never stretch the bitmap to manufacture a ratio. |
| A derived action pose drifts from an otherwise valid canonical structure | Preserve the canonical identity; redraw the affected semantic key pose or locally repair the affected frame, according to the defect. Recheck neighboring poses and dependent motion before interpolation or expansion. Reopen the canonical only if evidence locates the defect there. |
| An effect makes the character shrink | Preserve character occupancy and repair effect composition/layers within the selected format. |

If readability still needs a proportion change, treat it as a design revision
and use the existing authority/selection rules. Never silently switch an adult
source to Q, change package format, or enlarge an installation as a readability
fix outside the authorized scope.

## Compare, select and retain the result

When the proportion direction is unresolved, make a small, purposeful comparison
before detailed polishing. Hold identity, costume, pose/view, rendering style,
background and displayed body height as consistent as the experiment permits.
Vary the body relationships being tested, and record generation drift that
prevents a clean comparison. Show both equal-height structural views and the
intended desktop-size views, preserving aspect ratio. Do not require a fixed
candidate count or recreate an already selected design to fill a board.

The builder and independent reviewer judge the selected route's whole-body
coherence, recognition and desktop readability using the existing identity gate.
An exploratory comparison can answer a proportion preference without passing
full identity, animation or runtime checks; label its scope explicitly. Do not
present a known anatomical defect as a stylistic choice for the user to fix.
Record selection against the exact image/hash, describe why the body works,
and retain unresolved questions. A requested head count is not a measurement;
a preferred silhouette is not approval of face, costume or animation.

## Research basis and limits

- [Clip Studio: Chibi characters](https://www.clipstudio.net/how-to-draw/archives/155423) describes the common 2–4-head range and how torso/leg balance changes the impression. These are illustration heuristics, not a desktop-pet pass rule.
- [VRoid: SD character adjustment](https://vroid.pixiv.help/hc/en-us/articles/360014785994-Adjust-the-parameters-to-easily-create-a-SD-character) treats head size and limb length together when adapting a model.
- [Proko: Idealistic figures](https://www.proko.com/course-lesson/human-proportions-idealistic-figures) distinguishes natural and idealized figure conventions; neither governs every age, build or stylization.
- [Riot: Character art](https://www.riotgames.com/en/artedu/character-art) connects proportion, likeness, credible form and small-model readability, and recommends quick proportion prototypes.

The repair and review guidance above applies these ideas to DesktopCompanion;
it is not a claim that research establishes one ideal desktop-pet head count.
