# Production and QA

Use this reference to execute the Nangong Wan quality standard on a new or existing character.

## Required working records

### Evidence and identity

Record exact target, sources/locators, evidence class, source role, allowed use, conflicts, effect caster, and uncertainty. High-salience identity groups require current direct evidence. Historical same-character footage is motion support, not current identity.

Use one provenance status plus independent selection:

- `REQUIRED`: user/runtime constraint;
- `DERIVED`: computed from recorded inputs;
- `PROPOSED`: agent-originated;
- `APPROVED`: recorded user or governing-artifact approval;
- `selection: candidate|selected`: whether the value has passed its applicable gate.

An autonomous selected proposal remains `PROPOSED`, not `APPROVED`.

### Action portfolio and contract

For every action record:

- semantic ID, label, family/risk class, direction/form, evidence, and desktop role;
- entry, ordered semantic phases, exit, loop seam, interruption, and recovery;
- body/face/hands, hair/garment, occlusion, prop/effect state per phase;
- body/world anchor, body occupancy, permitted intentional motion, forbidden drift/scale changes;
- menu/manual eligibility, autoplay eligibility/pool, weight, cooldown/group, repeat, environmental conditions;
- frame order and per-frame duration;
- visual/runtime acceptance and maturity.

Frame count is an output of the phase chain, not an input quota.

## Batch envelope

Before unattended or multi-action production, record selected IDs, selected masters/pilots, maximum candidates per action, maximum targeted-repair attempts, checkpoints, wall-time/task budget where known, and forced-stop rules.

Stop when identity/evidence drifts, the route changes, the same causal defect recurs after one bounded repair, or a retry/budget limit is reached. A stopped batch returns candidates and a blocker; it does not lower acceptance.

## Generation and deterministic pipeline

An image-generation or edit request states:

- task type and role of every reference;
- exact era/form and identity locks;
- transparent canvas/cell geometry;
- exact grid order and per-cell semantic phase;
- stable features and permitted changes;
- hand/limb, prop, occlusion, effect, and anchor state;
- effect whitelist/blacklist;
- exclusions such as text, borders, unrelated characters/props, opaque backgrounds, clipping, and body-scale changes;
- preservation of unaffected cells for a targeted repair.

Deterministic tooling handles alpha, slicing, registration, composition, ordering, atlas geometry, and previews. Reject halos, destructive cutouts, clipped pixels, accidental empty cells, and bounding-box normalization that removes intended motion.

## Review artifacts

Static review:

- manifest-order labeled contact sheet;
- actual-size body/face crop when needed;
- checker, light, and dark background renders;
- identity, anatomy, direction, hands, cloth/hair, prop contact, occlusion, effect ownership, alpha, clipping, scale, and anchors.

Motion review:

- true manifest timings;
- entry, development, peak, hold, decay, recovery, return;
- loop seam, size popping, unwanted drift, intentional motion, interruption, and action meaning.

Runtime review:

- current schema and WebP decode/alpha;
- valid cells and cross-references;
- Registry and Catalog;
- menu/manual labels and playback;
- automatic eligibility/pools/weights/cooldowns/groups;
- direction, world-motion frames, screen-relative travel and edges;
- interruption, recovery, forms/sequences/restoration as applicable;
- actual launched build and isolated logs.

## Behavior validation

Do not promise equal long-run frequency from equal weights. For a stable weighted pool, record the oracle and method before testing; use at least five deterministic seeds and enough eligible choices for the lowest-probability candidate to have at least 100 expected selections. The default static-pool check is Pearson multinomial goodness-of-fit at `alpha=0.01` plus Bonferroni-adjusted two-sided 99% binomial intervals.

For cooldown/priority/stateful regimes, use the executable scheduler specification or governing tests. If no defensible expected distribution exists, verify reachability, cooldown, anti-streak, and starvation invariants and mark distribution `UNVERIFIED`.

Real-use soak evaluates perceptual dominance and experience, not statistical fairness.

## Causal repair matrix

| Failure | Repair layer |
|---|---|
| Wrong era, costume, ability, caster, or palette | Evidence/identity. |
| Wrong acting, locomotion, silhouette, or action meaning | Redraw master/key poses. |
| One hand, face, prop, or effect transition | Targeted frame edit; review neighbors. |
| Structurally correct stable interval is choppy | Limited in-between/interpolation. |
| Alpha, crop, cell order, registration, or anchor | Deterministic pipeline. |
| Menu, timing, weight, distance, cooldown, interruption | Manifest/runtime behavior. |
| Failure spans units after one bounded repair | Return to master, contract, or production strategy. |

Any upstream change invalidates every downstream claim it can affect. Retain the last-valid artifact hash and rerun affected gates.

## Maturity and reports

Primary maturity:

`research-candidate → identity-candidate → storyboard-candidate → production-frames → runtime-valid → installed-test → long-use-candidate → release-candidate`

- `installed-test` requires authorized in-app exercise.
- `long-use-candidate` means formal gates pass and soak remains.
- `release-candidate` means required soak passes; publication authority is still separate.
- `user-accepted` is optional evidence bound to the exact artifact/hash/gate shown.

Packaging is independent: `not-packaged|local-candidate|release-artifact`. A ZIP does not upgrade maturity.

The final review reports:

- exact target, selected evidence, masters, contracts, changed files, and immutable comparison set;
- artifact paths/hashes and full source → master → storyboard → frame → atlas → manifest chain;
- commands, exit codes, static/motion/in-app checks, and unverified items;
- `PASS` or `BLOCKED`, causal blocker, and minimum rework;
- local-only keep, archive candidate, cleanup candidate, and uncertain/user-owned items without deleting them.
