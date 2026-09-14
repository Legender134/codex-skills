# Look Direction Workflow

Read this reference only for its current stage. Apply the shared runtime, authorization, and routing rules in `../SKILL.md`. All skill-relative paths, including `references/...` and paths using `SKILL_DIR`, refer to the skill root. Generated `qa/...` and `decoded/...` paths refer to the current run directory.

## Required V2 Look-Direction Stage

Every new pet must complete this stage. After standard-row QA passes, write `qa/look-mechanics.md`, approve the four cardinals, synthesize and validate the complete `look-row-9`, then synthesize `look-row-10`. Row 10 becomes ready only after row 9 is deterministically registered, clears post-registration edge checks, and has no semantic or continuity hard failure; reviewed warnings may remain. It uses row 9 plus the approved cardinal strip as continuity evidence.

Before either look row, run the prepared `look-cardinals` strip job, extract its four cells with `extract_cardinal_anchors.py`, and approve them. Do not let a two-row sweep invent its own left/right basis. `090` must point toward the viewer's screen-right edge and `270` toward the viewer's screen-left edge; for faces, the nose tip and pupils must cross to the corresponding side of the head center. If one cardinal is ambiguous, regenerate only that anchor before continuing.

After copying row 9 into `decoded/look-row-9.png`, register and edge-check it with the same transform used by final assembly:

```bash
"$PYTHON" "$SKILL_DIR/scripts/assemble_extended_atlas.py" \
  --base-atlas "$RUN_DIR/final/spritesheet.webp" \
  --look-row-9 "$RUN_DIR/decoded/look-row-9.png" \
  --neutral-cell "$RUN_DIR/frames/idle/00.png" \
  --chroma-key "$CHROMA_KEY" \
  --chroma-threshold 96 \
  --registered-row-output "$RUN_DIR/qa/look-row-9-registered.png" \
  --registration-manifest-output "$RUN_DIR/qa/look-row-9-registration.json"
```

Inspect the eight registered cells at normal pet size in `000` through `157.5` order. Record the row-9 semantic and adjacent-continuity review, resynthesize the complete row for any hard failure, and mark `look-row-9` complete only after this check passes. That completion makes row 10 ready in `imagegen-jobs.json`.

Generate only the additional look-direction visuals with `$imagegen`:

- Required for new pets: two coherently synthesized 8-frame row strips, one for row 9 and one for row 10.
- Always include the canonical base reference and approved 8x9 contact sheet.
- Keep the body scale, baseline, head size, face, materials, palette, markings, and props consistent with the standard atlas.
- Before prompting, write a short look mechanics decision for this specific pet. First ask: **what is the best natural motion for this character when looking around?** Describe what stays anchored, what leads the gaze, what follows, and what bends, shifts, turns, squashes, stretches, or deforms. Include eyes and props: decide whether eyes rotate as physical eyeballs, irises move on a fixed surface, eyelids reshape, pupils slide, props stay stable, props lag slightly, or props move with the body. Use the character's physical construction as the guide: flexible wire should bend, soft bodies should deform, separate heads should turn, ears/fur/antennae may follow through, physical eyeballs should rotate as whole eye globes in their sockets, flat screen or sticker eyes may change their drawn features on a fixed surface, and rigid or screen-like characters may stay body-locked while facial features move.
- Define a motion budget before generation: each 22.5-degree step should move the same parts by roughly the same visual amount, with no single adjacent pair doing a larger bend, scale change, prop shift, or silhouette change unless the mechanics decision explicitly calls out that asymmetry. Generate row 9 first along `000 -> 090 -> 180`, then give completed row 9 to row 10 so `180` begins exactly one step after `157.5`. Row 10 follows `180 -> 270 -> 000`, and `337.5` in row 10 must land one step before the approved `000` in row 9.
- Do not use whole-sprite rotation, whole-cell rotation, skewing, or affine tilting to fake gaze direction. A direction row built by rotating the entire pet is failed unless the pet is literally a rotating rigid object and the look mechanics decision explicitly says the whole object should rotate. Whole-body tilt that makes the item/background appear to rock left or right is not natural look behavior for ordinary pets.
- Generate a coherent 16-pose gaze set, not 16 unrelated variants. Each direction should feel like a point on one continuous arc around the clock.
- The look mechanics decision must name the natural pose family for each cardinal direction before generation, including which body side becomes more visible, which features become occluded, and how any held prop follows or lags. Do not let the generator infer all directions from one front-facing pose. For characters with a face or head, leftward directions must visibly turn or bend the face/head left, rightward directions must visibly turn or bend right, up/down directions must use the eyes, eyelids, head angle, neck, and upper body as physically appropriate, and diagonals must interpolate between those pose families. A set where every cell remains essentially front-facing, or where all leftward cells still read as front/right-facing, is failed.
- Adjacent direction cells must have continuous body movement. Compare every neighboring pair in direction order, including `157.5 -> 180`, `337.5 -> 000`, and any row-strip boundary. Anchored parts must not jump, flip sides, or teleport between adjacent states; if a body part moves laterally, bends, stretches, or rotates, its position should progress gradually across the intervening directions.
- Do not mirror, re-center, or independently regenerate adjacent direction cells in a way that changes the pet's body registration. Keep a stable anchor, usually the feet/base/torso/lower body or the natural grounded part of the character, and let only the intended look mechanics change around it.
- Every look cell must be visually distinguishable from the neutral/resting frame at final pet size. A direction cell that reads as front-facing, idle, or neutral is failed even when it is non-empty, transparent, and in the correct row/column.
- Cardinal directions must be semantically unmistakable at final pet size, not only numerically or geometrically different. `000` must clearly read as looking up, `090` as looking right, `180` as looking down, and `270` as looking left using the pet's natural mechanism. If the pet has no pupils or physical eyeballs, the head, face surface, eyelids, antennae, ears, or body bend must carry the direction clearly enough that a viewer can identify the cardinal without labels.
- Diagonal and intermediate directions should broadly occupy the intended quadrant and advance naturally through the ordered loop. Minor pupil, nose, eyelid, or feature-placement deviations are not failures by themselves. Reject only gross wrong-quadrant poses, visible reversals, or intermediate cells that break the coherent motion family.
- For eyeless object pets, do not default to literal whole-object rotation just because the object is rigid. First identify whether the object has a natural front, display face, playable surface, readable silhouette, or iconic viewing angle. Preserve that primary readable face unless the user explicitly asks for turntable rotation. Express look direction through subtle object-specific body language: small lean, neck/tip aim, hinge, yaw, pitch, bend, vibration, squash, follow-through, or attached-part motion. The direction should read as attention or orientation, not as the object spinning through all clock angles.
- Preserve the pet's original eye design in look-direction cells. Do not paint new round "googly" eyes, replacement eye whites, floating pupils, detached eye dots, or a second eye layer on top of the source eyes. Eye motion must follow the look mechanics decision. If the pet has physical eyeballs, rotate or redraw the whole eyeball surface so the sclera/eye white, iris, pupil, eyelids, rim, and highlights change together as one physical eye; do not slide only the iris or pupil across a fixed eye white. If the pet has flat printed, sticker, or screen eyes, keep the surface fixed and move/redraw only the features that would physically change on that surface. Do not use procedural pupil/iris compositing unless it is clipped to the original eye aperture and visibly remains inside the head silhouette in every direction. If the original eye design cannot be preserved cleanly, regenerate the whole look cell with the original eye construction instead of compositing new eyes over it.
- Eyes may lead the gaze, but pupil-only motion is an exception, not the default. Use it only when the look mechanics decision explains why whole-eye rotation, eyelid reshaping, body, head, or feature movement would be unnatural for that specific design. Large-eye pets, cyclops pets, and round rigid-body pets with physical eyeballs usually should rotate the whole eye globes, not use pupil-only or googly-eye sliding. Screen-face pets and printed-eye pets may be body-locked with feature motion only. Separate head/body pets should usually combine eye movement with head turn, head tilt, ear/fur/upper-body follow-through, and a stable torso. Rigid object mascots may hinge, flex, slide, or shift attached features without rotating the whole sprite. Flexible wire or paperclip-like mascots should usually keep the feet/base anchored while the upper loop or face area bends toward the target and held props remain stable or lag subtly. Blob or organic pets should usually keep a base anchored while the face/head area stretches subtly toward the target. Other pet types should get their own similarly grounded mechanics.
- Human or humanoid pets need persona-preserving look mechanics. Do not use broad non-rigid raster warps that stretch the skull, brows, mouth, hoodie, hands, or held props just to make a direction read. The eyes should usually lead the gaze with visible eye, eyelid, and eyebrow participation, then the head/neck and upper body should follow subtly; a humanoid row where the head moves but the eyes stay locked in one expression is failed unless the mechanics decision gives a specific physical reason. Use small eye rotation, eyelid/eyebrow changes, head/neck turn, and restrained upper-body follow-through while preserving facial proportions and expression. Programmatic repairs must move anatomical parts with rigid or near-rigid part motion, not displacement fields that change facial feature spacing. For pets with held, worn, or attached props, infer each prop's physical constraints before generating look directions: where it is anchored, whether it is rigid or flexible, whether it leads or lags the body, and how it should occlude or be occluded as the character turns. Props near the face may become more side-on, partly hidden by the head, or reveal different contact points; hand-held tools may swing or lag subtly while staying attached; worn props should follow the body; flexible cords or straps should arc continuously. Do not keep the prop and character in the same front-facing relationship across all look directions. Before packaging a humanoid pet, inspect the normal-size neutral and cardinal cells together and reject identity or facial-proportion drift, or a `270` cardinal that does not unmistakably read as left.
- For every pet, use cardinal anchors instead of trusting a two-row sweep to preserve left/right semantics. Generate `000`, `090`, `180`, and `270` together as one strip, then extract and approve them. The final look rows use those four pose families for direction meaning and interpolate the intermediate directions as a coherent arc. Define directions in viewer/screen coordinates, never character-relative coordinates. Do not require exact pupil or nose placement on intermediate poses; use the ordered loop and overall quadrant motion as the primary evidence.
- Keep motion subtle and pet-safe: preserve volume, baseline, silhouette readability, identity, and material believability. The look pose may involve head, eyes, face, upper body, appendages, or body deformation only when those parts would naturally participate.
- Do not add labels, degree text, arrows, clocks, guide marks, shadows, glows, scenery, or detached effects.

Direction order is fixed:

```text
row 9:  000, 022.5, 045, 067.5, 090, 112.5, 135, 157.5
row 10: 180, 202.5, 225, 247.5, 270, 292.5, 315, 337.5
```

`000` means looking up / 12 o'clock. Neutral/front is the pointer deadzone and should fall back to idle unless the target renderer explicitly uses a neutral cell.

### Direction Acceptance Policy

Judge the completed 16-pose loop as an animation family. Cardinals must match their single axis exactly. Intermediate directions should preserve the intended axes, but isolated blind-review uncertainty is evidence for labeled loop review rather than an automatic regeneration trigger.

Hard failures require row regeneration:

- a cardinal anchor is wrong or ambiguous: `000` up, `090` screen-right, `180` down, or `270` screen-left
- a blind cardinal classification contradicts or cannot confirm `000` up, `090` screen-right, `180` down, or `270` screen-left
- labeled normal-size review confirms that an intermediate pose points into the wrong principal quadrant, reverses the loop, or loses a required axis badly enough to read as a different direction
- the ordered loop visibly reverses, backtracks, crosses into the wrong principal quadrant, or contains a conspicuous snap, identity change, scale pop, registration jump, or broken prop attachment
- the source or atlas has a deterministic structural failure, or visual review confirms clipping, an accidental transparent interior hole, a seam band, replacement eyes, or a materially broken sprite
- whole-sprite rotation, deformation, or eye mechanics visibly break the pet's identity or make the motion feel incoherent

Review warnings do not require regeneration by themselves:

- an intermediate pose is similar to a neighbor, a diagonal cue is subtle, or the pet uses less body movement than the ideal mechanics plan
- blind reviewers disagree, return `ambiguous`, or produce an opposite-sign majority for an intermediate direction, provided labeled normal-size review confirms the intended direction and the ordered loop remains coherent
- continuity metrics report a diff, center, area, or alpha-hole candidate without a visible snap, pop, seam, or broken silhouette in the QA sheet or animation loop

Before accepting the v2 atlas, create a focused direction QA sheet showing the neutral/rest frame next to all 16 look cells, labeled by degree and expected direction, at approximately the in-app display size. Run the adjacent continuity measurement separately and treat its findings as motion-review evidence, not automatic direction failures.

Perform an explicit semantic review for every direction and record `pass`, `warning`, or `fail`, plus separate visible evidence for its horizontal and vertical axes. A warning may accept blind-review uncertainty for an intermediate pose when labeled normal-size review confirms the intended axes and the ordered loop remains coherent. It may not waive a wrong or ambiguous cardinal, a labeled wrong-quadrant pose, or a visible reversal. If a direction receives `fail`, strengthen the containing row's instructions and resynthesize that complete coherent row. Never replace the final normalized cell directly.

Look rows must have transparent backgrounds after assembly. Do not accept or install the pet if `qa/look-directions.png` or `qa/contact-sheet-extended.png` shows chroma-key panels behind any look cell. If generated look rows contain slight chroma-key lighting variation, rerun assembly with a wider `--chroma-threshold` instead of packaging the opaque key color. Validation must pass without opaque chroma-key-pixel errors.

Extended look cells must also keep the same practical scale and body registration as the neutral/default pet. Do not accept a direction set where neutral/default is noticeably larger than the look cells, where the look cells appear to float above the baseline, or where the pet slides left/right within its 192x208 cell while only changing gaze. Extended assembly recovers each pose group from the complete original-resolution row and computes one shared scale from height plus every pose's left and right extents around the shared lower-body anchor, so asymmetric poses remain inside the final cell after alignment. It resizes each original crop exactly once and never enlarges an already-resampled cell. The neutral frame supplies the target body height, lower-body anchor, and baseline. Pass `--neutral-cell` when an external neutral frame is available; otherwise the assembler falls back to the populated neutral/default slot or first visible idle frame in the base atlas. If the focused QA sheet still shows scale or placement drift, repair before packaging.

Assemble the extended atlas from two generated row strips:

Use the run's selected chroma key for every assembly path; omitting it falls back to green and can misclassify a magenta background as clipped sprite pixels.

```bash
CHROMA_KEY=$(jq -r '.chroma_key.hex' "$RUN_DIR/pet_request.json")
```

Extended assembly reuses the approved registered row-9 cells and persisted scale exactly. It removes the chroma background from row 10, detects its eight separated pose groups, preserves their left-to-right order, crops each complete pose without fixed-slot slicing, and fits them against the same neutral-frame scale, lower-body anchor, and baseline. Only then does it apply the near-edge clipping check to row 10's normalized `192x208` cells. If pose-group recovery is ambiguous, or if row 10 cannot fit the approved row-9 transform without failing the post-registration edge check, resynthesize row 10; do not rescale row 9, patch an individual final cell, or relax the threshold for acceptance.

```bash
"$PYTHON" "$SKILL_DIR/scripts/assemble_extended_atlas.py" \
  --base-atlas "$RUN_DIR/final/spritesheet.webp" \
  --registered-row-9 "$RUN_DIR/qa/look-row-9-registered.png" \
  --row-9-registration "$RUN_DIR/qa/look-row-9-registration.json" \
  --look-row-10 "$RUN_DIR/decoded/look-row-10.png" \
  --neutral-cell "$RUN_DIR/frames/idle/00.png" \
  --chroma-key "$CHROMA_KEY" \
  --chroma-threshold 96 \
  --output "$RUN_DIR/final/spritesheet-extended.png" \
  --webp-output "$RUN_DIR/final/spritesheet-extended.webp" \
  --manifest-output "$RUN_DIR/final/spritesheet-extended.json"
```

For repair or upgrade of a user-provided 16-cell source that was already approved as one coherent set, individual-cell assembly remains available. Do not use this path for newly generated repair cells:

```bash
"$PYTHON" "$SKILL_DIR/scripts/assemble_extended_atlas.py" \
  --base-atlas "$RUN_DIR/final/spritesheet.webp" \
  --look-cells-dir /absolute/path/to/look-cells \
  --neutral-cell "$RUN_DIR/frames/idle/00.png" \
  --chroma-key "$CHROMA_KEY" \
  --chroma-threshold 96 \
  --output "$RUN_DIR/final/spritesheet-extended.png" \
  --webp-output "$RUN_DIR/final/spritesheet-extended.webp" \
  --manifest-output "$RUN_DIR/final/spritesheet-extended.json"
```

Run the single deterministic edge-local spill-suppression pass on the assembled v2 atlas, then validate and make a contact sheet:

```bash
"$PYTHON" "$SKILL_DIR/scripts/despill_chroma_edges.py" \
  "$RUN_DIR/final/spritesheet-extended.png" \
  --output "$RUN_DIR/final/spritesheet-extended.png" \
  --webp-output "$RUN_DIR/final/spritesheet-extended.webp" \
  --chroma-key "$CHROMA_KEY" \
  --json-out "$RUN_DIR/qa/chroma-despill-extended.json"
```

Treat `qa/chroma-despill-extended.json` as the authoritative chroma result. When it has `ok: true` and `validate_atlas.py --require-v2` passes, do not fail visual QA for perceived magenta fringe, regenerate any row, rerun despill, tune thresholds, or create an additional chroma-repair script. If either deterministic check fails, stop with a pipeline failure instead of retrying image generation.

This is the only chroma-cleanup invocation in the workflow. The intermediate 8×9 atlas is never despilled; rows `0-8` and the newly assembled look rows `9-10` are cleaned together exactly once in the completed 8×11 atlas.

```bash
"$PYTHON" "$SKILL_DIR/scripts/validate_atlas.py" \
  "$RUN_DIR/final/spritesheet-extended.webp" \
  --json-out "$RUN_DIR/final/validation-extended.json" \
  --chroma-key "$CHROMA_KEY" \
  --require-v2
```

```bash
"$PYTHON" "$SKILL_DIR/scripts/make_contact_sheet.py" \
  "$RUN_DIR/final/spritesheet-extended.webp" \
  --output "$RUN_DIR/qa/contact-sheet-extended.png"
```

Create the focused direction QA sheet:

```bash
"$PYTHON" "$SKILL_DIR/scripts/make_direction_qa_sheet.py" \
  "$RUN_DIR/final/spritesheet-extended.webp" \
  --output "$RUN_DIR/qa/look-directions.png"
```

Create the blind horizontal-and-vertical axis challenge and keep its answer key away from the visual QA worker:

```bash
"$PYTHON" "$SKILL_DIR/scripts/make_direction_blind_qa_sheet.py" \
  "$RUN_DIR/final/spritesheet-extended.webp" \
  --output "$RUN_DIR/qa/direction-blind-pairs.png" \
  --answer-key "$RUN_DIR/qa/direction-blind-answer-key.json"
```

Give three fresh isolated workers only `qa/direction-blind-pairs.png`. Each row states whether to classify the horizontal or vertical axis. Every worker must classify A and B as `screen-left`, `screen-right`, `up`, `down`, or `ambiguous` as appropriate, without seeing degree labels, expected directions, the labeled direction sheet, the answer key, or another worker's verdicts. Write their classifications separately, then combine them by strict per-cell majority:

```bash
"$PYTHON" "$SKILL_DIR/scripts/combine_direction_blind_verdicts.py" \
  --verdicts "$RUN_DIR/qa/direction-blind-verdicts-1.json" \
  --verdicts "$RUN_DIR/qa/direction-blind-verdicts-2.json" \
  --verdicts "$RUN_DIR/qa/direction-blind-verdicts-3.json" \
  --json-out "$RUN_DIR/qa/direction-blind-verdicts.json"
```

Apply the hidden answer key only to the consensus verdict:

```bash
"$PYTHON" "$SKILL_DIR/scripts/validate_direction_blind_verdicts.py" \
  --answer-key "$RUN_DIR/qa/direction-blind-answer-key.json" \
  --verdicts "$RUN_DIR/qa/direction-blind-verdicts.json" \
  --json-out "$RUN_DIR/qa/direction-blind-validation.json"
```

The hidden answer key contains seven horizontal pairs and seven vertical pairs. The cardinal pairs (`000` vs `180` and `090` vs `270`) are hard gates: a mismatch or ambiguous majority keeps validation at `ok: false`. All intermediate pairs are review gates: mismatches, same-direction votes, and ambiguous majorities are preserved as warnings while validation remains `ok: true`. The blind pass is mandatory, but intermediate warnings are resolved by labeled normal-size loop review instead of repeated regeneration by default.

### Blind Review Severity Resolution

After receiving a blind or final visual QA `pass`/`fail` result:

1. If it passes, continue immediately.
2. If it fails, inspect the worker's semantic reasons, repair note, labeled direction sheet, `qa/direction-semantics.json`, and `qa/look-continuity.json` before regenerating anything.
3. Classify the failure as `major` or `minor`:
   - `major`: wrong or ambiguous cardinal; labeled normal-size review confirms a wrong principal quadrant or visible reversal; conspicuous snap, scale pop, identity change, broken attachment, clipping, interior seam/hole, or deterministic validation failure.
   - `minor`: exact pupil or nose placement differs from the numerical ideal; a near-vertical horizontal cue is subtle; isolated reviewers disagree or return `ambiguous`; an intermediate blind majority conflicts but the labeled ordered loop still reads correctly; continuity metrics warn without a visible defect.
4. Major failures require repair. Minor failures may be overridden and the installation pipeline continues.
5. Record every override in `qa/blind-review-resolution.json` with `decision: "accept"`, `severity: "minor"`, the failed checks, the labeled/continuity evidence that makes them acceptable, and `reviewed_by: "parent"` or `"user"`. Never override a major failure.

An override is a deliberate visual judgment, not a way to silence missing evidence. The blind sheet, consensus verdicts, validation output, labeled semantics, continuity report, and resolution file all remain in the final QA artifacts.

Measure adjacent direction continuity:

```bash
"$PYTHON" "$SKILL_DIR/scripts/measure_direction_continuity.py" \
  "$RUN_DIR/final/spritesheet-extended.webp" \
  --json-out "$RUN_DIR/qa/look-continuity.json"
```

Visually QA `qa/contact-sheet-extended.png`, `qa/look-directions.png`, and `qa/look-continuity.json` before accepting. Inspect the 16 normal-size look cells as an ordered loop, not only as isolated stills. For every direction label, compare the expected direction to the visible gaze/body direction and record `pass`, `warning`, or `fail` in `qa/direction-semantics.json`. Reject only the hard failures in the Direction Acceptance Policy. Record subtler semantic or metric concerns as warnings and accept them when the loop remains cohesive, readable, identity-preserving, and visually pleasing at normal pet size.

If a blind or final visual QA worker returns `fail`, apply Blind Review Severity Resolution before queuing a repair. Continue packaging when the failure is minor and `qa/blind-review-resolution.json` records the accepted override.

Only after all deterministic and visual QA passes, package the approved extended spritesheet as a v2 pet. `spriteVersionNumber: 2` is mandatory; without it the app defaults to the 9-row v1 contract and rejects the 2288-pixel-tall asset.

```bash
PET_ID=$(jq -r '.pet_id' "$RUN_DIR/pet_request.json")
DISPLAY_NAME=$(jq -r '.display_name' "$RUN_DIR/pet_request.json")
DESCRIPTION=$(jq -r '.description' "$RUN_DIR/pet_request.json")
PET_DIR="${CODEX_HOME:-$HOME/.codex}/pets/$PET_ID"
mkdir -p "$PET_DIR"
cp "$RUN_DIR/final/spritesheet-extended.webp" "$PET_DIR/spritesheet.webp"
jq -n --arg id "$PET_ID" --arg displayName "$DISPLAY_NAME" --arg description "$DESCRIPTION" \
  '{id: $id, displayName: $displayName, description: $description, spriteVersionNumber: 2, spritesheetPath: "spritesheet.webp"}' \
  > "$PET_DIR/pet.json"
```

Write `qa/run-summary.json` after packaging:

```bash
jq -n --arg run_dir "$RUN_DIR" --arg spritesheet "$RUN_DIR/final/spritesheet-extended.webp" --arg validation "$RUN_DIR/final/validation-extended.json" --arg chroma_despill "$RUN_DIR/qa/chroma-despill-extended.json" --arg contact_sheet "$RUN_DIR/qa/contact-sheet-extended.png" --arg direction_sheet "$RUN_DIR/qa/look-directions.png" --arg direction_semantics "$RUN_DIR/qa/direction-semantics.json" --arg blind_direction_validation "$RUN_DIR/qa/direction-blind-validation.json" --arg blind_review_resolution "$RUN_DIR/qa/blind-review-resolution.json" --arg continuity "$RUN_DIR/qa/look-continuity.json" --arg review "$RUN_DIR/qa/review.json" --arg package "$PET_DIR" '{ok: true, spriteVersionNumber: 2, run_dir: $run_dir, spritesheet: $spritesheet, validation: $validation, chroma_despill: $chroma_despill, contact_sheet: $contact_sheet, direction_sheet: $direction_sheet, direction_semantics: $direction_semantics, blind_direction_validation: $blind_direction_validation, blind_review_resolution: $blind_review_resolution, continuity: $continuity, review: $review, package: $package}' > "$RUN_DIR/qa/run-summary.json"
```

After all QA and packaging succeed, keep `pet_request.json`, `final/spritesheet-extended.webp`, `final/validation-extended.json`, `qa/chroma-despill-extended.json`, `qa/contact-sheet-extended.png`, `qa/look-directions.png`, `qa/direction-semantics.json`, `qa/direction-blind-pairs.png`, `qa/direction-blind-answer-key.json`, `qa/direction-blind-verdicts.json`, `qa/direction-blind-validation.json`, `qa/blind-review-resolution.json` when an override was used, `qa/look-continuity.json`, `qa/previews/`, `qa/review.json`, and `qa/run-summary.json`. Keep prompts, layout guides, generated row strips, extracted frames, PNG intermediates, the 8x9 intermediate atlas, and the job manifest until exact cleanup targets are authorized. Report them as archive or cleanup candidates; successful QA is not deletion permission.
