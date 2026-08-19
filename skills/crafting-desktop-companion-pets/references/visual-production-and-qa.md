# Visual Production and QA

## Production order

1. Lock the selected identity master and action/form contract.
2. Make readable key poses first, including contact, anticipation, peak, recovery, transitions, and form boundaries as applicable.
3. Generate intermediate frames only within structurally stable neighboring poses. Use independent poses or layered composition for changing limbs, depth, occlusion, face direction, garment, prop, weapon, or form.
4. Remove backgrounds and extract frames with a deterministic local/CLI pipeline where available. Preserve alpha; reject opaque backgrounds, halos, destructive cutouts, and clipped subject pixels.
5. Register, composite, and assemble only mapped selected frames. Derived atlas geometry and anchors must cite their inputs.

## Visual review gates

Review at actual pet size on a transparent checker, light background, and dark background. Inspect contact boards and motion previews for identity, anatomy, silhouette, facing/gaze, baseline/anchor stability, palette, alpha edges, clipping, size popping, cadence, and action meaning.

| Situation | Required review |
|---|---|
| Gaze | Inspect readable screen-coordinate gaze directions at pet size, including continuity between neighbors. |
| Transition or interpolation | Check the source/destination and every generated interval for pose continuity, occlusion, prop handoff, and anchor stability. |
| v4 layers | Check exactly one body hit-test layer, body-only interaction, stable public anchors, and no effect-driven dragging/position jump. |
| v4 quality | Review every action frame in both full and simplified quality; both must render and retain the intended body/anchor behavior. |
| Form change, transformation, or sequence | Preview enter/resident/exit and `formAfter` boundaries, repeats/holds, safe stop, pending, restore, and cleanup. |

## Repair and convergence

After each batch, perform agent self-review; do not substitute schema success or smooth playback for visual acceptance. Repair the smallest failing unit: master, key pose, interval, layer, atlas cell, mapping, configuration, or test. Re-run every gate affected by that repair.

If the same class of defect recurs after a bounded local repair attempt or failure spans multiple units, stop patching symptoms: return to the nearest faulty master, action contract, production strategy, or layer composition and revise it before retrying. Converge only when all applicable visual and runtime gates pass. Require user visual approval only if requested or if a subjective ambiguity has no safe evidence-based resolution.
