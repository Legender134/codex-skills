# Actions and Motion

Read this for an action expansion, motion repair, prop/effect work, movement,
or interruption design. It owns semantic action contracts; [Generation Job
Graph](generation-job-graph.md) owns batching and dependency state.

## Build a portfolio by role

Select actions because they add character and desktop-use coverage, not because
they fill slots. Consider persistent presence (idle, breathing, blink, and
temperament), ordinary left/right movement, quiet daily actions, distinctive
prop interactions, restrained abilities, source-owned signature abilities,
and any required safe entry, interruption, recovery, or return. An action must
add a distinct silhouette, energy, timing, or character meaning. Runtime
minimums are loadability floors, not a quality quota.

## Write semantic phases before frames

Use only the phases the action needs:

```text
entry/anticipation → preparation → development → peak → semantic hold → release/decay → recovery → return
```

Record body, face, hands, hair/garment, occlusion, prop/effect state, anchor,
duration, and key-pose status for every selected phase. Create an independent
key pose whenever anatomy, direction, hand state, depth/occlusion, garment,
prop/effect structure, or form changes. Add an intermediate only between
structurally stable neighbors. Frame count and duration follow semantic events;
do not duplicate near-identical cells, shift a whole sprite, or interpolate to
conceal missing acting.

Use the machine-readable [Action contract](../templates/action-contract.json)
for state, identities, phases, stable features, allowed/forbidden changes,
interruption, and behavior. The JSON contract—not a fixed number of Markdown
rows—defines the executable fields.

## Preserve lifecycles and anchors

Props progress through `introduced → acquired → used → released/consumed →
absent`. Effects progress through `origin → growth/travel → peak → decay →
cleanup`. Establish caster ownership in [Identity and
Evidence](identity-and-evidence.md) before using either lifecycle.

Use a body anchor for a character-relative phase and a world anchor only for a
declared travel phase. Fixed-canvas registration removes accidental jitter but
must preserve intentional hover, arc, recoil, and other approved anchor motion.
Record safe interruption phases and a recovery action or semantic return.

## Separate ordinary and exceptional movement

Ordinary locomotion is sustainable, directional, cyclic acting with changing
key poses, cloth/hair response, and a readable seam. Standing art translated
across the desktop is a concept failure.

Exceptional movement is a different family: anticipation or transformation,
declared travel, arrival, and recovery. World position changes only in recorded
travel phases. It needs visibly distinct distance, lower frequency, and a safe
edge policy. [Behavior and Soak](behavior-and-soak.md) owns the scheduler,
distance basis, bounds, and long-use policy.

## Keep the character readable in effects

Judge approved body occupancy independently from an effect’s full extent. For a
large effect, redesign composition, crop, layer strategy, or package route
before shrinking the canonical body. Read [Format v4](format-v4.md) when
separate layers or a larger effect canvas are needed, and [Visual QA](visual-qa.md)
for the required static and timed reviews.
