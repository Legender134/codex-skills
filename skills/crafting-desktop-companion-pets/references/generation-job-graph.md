# Generation Job Graph

Read this before an unattended batch, generation retry, or dependency change.
It owns job state, readiness, generation granularity, and hash invalidation;
[Repair and Convergence](repair-and-convergence.md) owns the causal strategy
decision.

## Separate visual generation from deterministic work

Generate identity candidates and semantic key poses with visual tools. Use
deterministic tooling for alpha cleanup, extraction, fixed-canvas registration,
composition, cell order, atlas assembly, contact sheets, timed previews, hashes,
and reports. Scaling, cropping, translation, or interpolation cannot repair
identity, anatomy, action meaning, or clothing structure.

Choose the smallest safe generation unit:

| Change class | Generation unit |
|---|---|
| Initial identity | one complete target-specific candidate |
| Small structurally stable action | a controlled strip may be appropriate |
| Body direction, hands, garment, or occlusion changes | independent semantic key poses |
| Stable neighboring poses | limited deterministic or guided intermediates |
| Large effect | preserve the selected body; use a layer or larger action canvas if needed |
| Form or sequence | independent enter, resident, and exit work |

Except for an initial identity candidate, every visual job carries the selected
canonical identity and the relevant action inputs. A layout reference controls
only order, placement, and safe margins.

Before constructing downstream generation jobs, recompute the identity gate
from the canonical file/hash, selected reference records, and ordered builder
and independent verdict files. Do not trust a self-asserted
`identityGateStatus` or opaque verdict IDs; the persisted identity contract must
exactly match the evaluated internal-pass IDs.

## Write the generation or edit request

Every generation or edit request records:

| Request content | Follow the owning reference |
|---|---|
| task type and the role of every reference | [Identity and Evidence](identity-and-evidence.md) |
| exact era/form and identity locks; stable features and permitted changes | [Identity and Evidence](identity-and-evidence.md) and [Canonical Identity and Proportions](canonical-identity-and-proportions.md) |
| transparent canvas/cell geometry | the applicable [Format v2](format-v2.md), [Format v3](format-v3.md), or [Format v4](format-v4.md) reference |
| exact grid order and per-cell semantic phase | [Actions and Motion](actions-and-motion.md) and the applicable format reference |
| anatomy, prop, occlusion, effect, and anchor state | [Actions and Motion](actions-and-motion.md) |
| effect whitelist/blacklist | [Identity and Evidence](identity-and-evidence.md) |
| exclusions: text, borders, unrelated characters/props, opaque backgrounds, clipping, and body-scale changes | [Visual QA](visual-qa.md) |
| preservation of unaffected cells for a targeted repair | [Repair and Convergence](repair-and-convergence.md) |

This request contract names inputs and points to their owners; it does not
duplicate the [Job manifest](../templates/job-manifest.json) schema or a
version-specific package schema.

## Prove pilots before expansion

Before unattended or multi-action expansion, require one passing representative
pilot for every planned risk class:

| Risk class | Pilot must prove |
|---|---|
| `identity/idle` | recognition, body scale, alpha, anchor, and readable breathing/blink cadence |
| `prop interaction` | introduction, ownership, hand contact, occlusion, use, and disappearance |
| `cyclic locomotion` | travel silhouette, directional design, cloth/hair response, and loop seam |
| `burst/transformation` | anticipation, travel-only displacement, endpoint recovery, distance, and safe edges |
| `large/layered effect` | caster ownership, body readability, canvas/layer strategy, peak, and cleanup |
| `form/sequence` | enter, resident, exit, safe stop, restore, and cleanup |

A successful pilot in one risk class does not authorize another risk class. A
high-information pilot may exercise several concerns, but every planned class
still needs its own passing evidence before its batch expands.

High-ambiguity evidence/effects or a multi-risk batch requires a fresh-context
second review, or an explicit recorded limitation when that review is
unavailable.

## Record a bounded batch envelope

Before unattended or multi-action production, record the selected IDs, selected
masters/pilots, maximum candidates per action, maximum targeted-repair attempts,
checkpoints, wall-time/task budget where known, and forced-stop rules. Stop the
batch when identity/evidence drifts, the route changes, the same causal defect
recurs after one bounded repair, or a retry/budget limit is reached. Return the
candidates and blocker; do not lower acceptance to continue the batch.

## Record the graph

Use [Job manifest](../templates/job-manifest.json). Every job records a stable
ID, kind, route/format, state, dependencies, input hashes, artifact hash,
selected canonical identity hash, action or prompt/contract inputs, expected
geometry, semantic phase, stable/allowed/forbidden features, separate technical
and visual verdict IDs, retry count, and any failure/next-strategy evidence.

The legal forward path is:

~~~
pending → ready → generating → candidate → technical-pass → visual-pass → selected
~~~

Any active state can move to blocked, superseded, or rejected. A terminal
failure never moves forward under the same job ID. A job becomes ready only
when every dependency is selected and its recorded hash matches; technical
and visual verdict fields remain separate.

## Invalidate precisely

When an upstream canonical or dependency artifact hash changes, preserve the
last valid artifact and supersede only the transitive descendants whose claim
depends on it. Clear their technical and visual verdict claims; leave unrelated
jobs unchanged. Do not use a new hash to retroactively select a stale
descendant.

Record a blocked/rejected job’s visible failure, root condition, one changed
variable, preserved passing properties, retry count, and next strategy. On a
repeated causal root condition, the next strategy must change causal inputs;
prompt-wording-only is not a sufficient recurrence strategy. Read [Repair and
Convergence](repair-and-convergence.md) for the repair-layer table.
