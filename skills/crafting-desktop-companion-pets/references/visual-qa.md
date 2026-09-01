# Visual QA

Read this for visual review, alpha/frame/atlas repair, a package check, runtime
verification, or handoff. It owns the gate sequence and the boundary between
technical evidence and visual acceptance.

## Apply gates in order

Run the applicable gate as soon as its artifact exists. An upstream failure
preserves earlier evidence but blocks dependent maturity claims.

| Gate | Decide |
|---|---|
| Source | target identity, proportion, action semantics, anatomy, hair/clothing, prop/effect ownership, and crop |
| Extraction | frame count/order, alpha, components, clipping, and fixed canvas |
| Static | manifest-order contact sheet, actual-size readability, light/dark/checker views, identity, and anchors |
| Motion | true durations, phase readability, peak/hold/decay, loop seam, drift, size jump, interruption, and recovery |
| Format | version geometry, alpha, mappings, references, and decode |
| Runtime | Registry, Catalog, menu/manual path, scheduler, direction, bounds, interruption/recovery, and launched logs |
| Behavior | long-use eligibility, cooldown/group effects, reachability, and desktop experience |

Inspect actual runtime size before enlarged detail. Use inspect_frames.py for
ordered technical diagnostics, make_contact_sheet.py for manifest-order static
review, and render_timed_previews.py for true-duration technical evidence. None
of those tools awards visual acceptance.

## Inspect every generated cell and frame

Review every generated cell/frame in manifest order; sampling is not permitted.
Reject halos, destructive cutouts, clipped pixels, accidental empties, or
normalization that removes intended motion.

## Keep internal review ahead of user acceptance

Use this visual handoff order for identity, actions, motion, and the assembled
pet:

1. The builder self-reviews the complete applicable comparison set at actual
   size. Any known source-likeness, aesthetic-coherence, anatomy, continuity,
   alpha, or runtime-visible defect returns to causal repair; it is not
   `READY_FOR_REVIEW`. Record a hash-bound builder visual verdict when it passes.
2. A read-only independent reviewer inspects the evidence, hashes, boards,
   previews, frames, and applicable runtime evidence and returns `PASS` or
   `BLOCKED`. `BLOCKED` returns to [Repair and
   Convergence](repair-and-convergence.md), not to the user. Record the
   independent verdict after the builder verdict against the same artifact.
3. Only an internally passing artifact may be presented for user acceptance.
   Ask the user only for a genuine preference among internally passing
   candidates, an irreducible subjective ambiguity, or a decision/authority
   reserved to the user. Never ask the user to discover, confirm, or prioritize
   a defect already visible internally.

An unavailable independent reviewer is a recorded blocker, not permission to
use the user as fallback QA. User availability, deadline, sunk cost, technical
green checks, or completed downstream work cannot bypass this order. Internal
`PASS` makes an artifact eligible for user acceptance; it does not grant user
acceptance or any installation/publication authority.

## Keep verdict types separate

Technical status can be unverified, partial, or pass for its specific check.
Visual status is a review decision tied to the reviewed artifact hash, gate,
scale, reviewer, observations, and blockers in [Visual
verdict](../templates/visual-verdict.json). A visual identity pass requires an
actual-runtime-size review by an independent reviewer. A technical
script can report diagnostics but cannot pass an aesthetic or likeness gate.

Keep package/schema success, Registry/Catalog evidence, launched-runtime
evidence, and visual acceptance as separate records. A valid schema proves
shape; it does not prove readable acting, package admission, scheduler behavior,
or in-app experience. In the run summary, retain the matching builder and
independent internal pass records for every artifact/gate sent for user
acceptance. Give the builder pass, independent pass, and user acceptance
strictly increasing positive `reviewSequence` values in that order; user
acceptance alone never changes `visualStatus` to `pass`.

## Review effects and motion causally

At each visual gate, compare body occupancy independently from effect extent;
a large effect may not shrink the selected body. For ordinary locomotion, reject
a slide even if timing, bounds, and mappings pass. For a local defect, review
neighboring frames before choosing the causal repair scope. Read [Actions and
Motion](actions-and-motion.md) for what an action must communicate and [Repair
and Convergence](repair-and-convergence.md) for the minimum repair layer.

## Record the result

Bind commands, exit codes, artifact paths/hashes, observations, blockers, and
unverified checks to the applicable verdict. The final aggregation belongs in
[Run summary](../templates/run-summary.json); status, authority, and local-state
classification remain independent from the QA verdict.
