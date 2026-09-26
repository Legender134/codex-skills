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

An assembled board may be scaled down by its viewer. Inspect the actual-size
panel separately at 1:1 or in the target runtime before claiming desktop
readability. The identity-sheet helper resizes the entire input canvas to its
`runtime_height`; it does not infer body occupancy, display scaling or DPI.
Use the intended full-frame height and distinguish this simulation from a
runtime capture.

## Scope exploratory review

Before canonical selection, review a style/proportion comparison for the
question it is meant to answer: structural coherence, readable differences and
controlled variables. Record unresolved identity, costume, alpha or motion
claims explicitly. A comparison pass permits a preference decision within that
scope; it cannot supply the `identity` pass required for action production.
Use a scoped `visual` verdict with the comparison artifact/hash and observations,
not a fabricated canonical selection. Existing internal review still applies.

The executable identity gate accepts only explicit `gate: "identity"` passes.
Generic `visual` records, including older records, remain valid for their stated
scope but cannot select identity or unlock action jobs, even for the same image
hash. To resume an older run that used that alias, review the unchanged candidate
against the full identity requirements and record explicit builder and independent
identity verdicts. Preserve the old records; do not merely relabel them or
regenerate already-valid art. A gate label alone does not prove a review occurred.

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

Internal PASS also permits already-authorized downstream production. Do not add
a mandatory user pause at every gate unless the user explicitly reserved that
choice. Acceptance of a specific image and authorization to produce candidates
are different records. Use an available read-only reviewer with exact artifact
hashes and comparison inputs; do not repeatedly ask whether to arrange review.

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

Before setting `formalGates: "pass"` in a run summary, declare the complete
current review scope in `requiredVisualReviews`. Each entry contains
`artifactPath`, `artifactSha256` and `gate`, matching the subjects in the internal
pass records below. Include the applicable identity, selected-action/motion and
actual-size/playback subjects for the deliverable being summarized; a canonical
or static comparison alone cannot represent the animated package. Use the
selected contracts to determine that scope, not whichever reviews happen to pass.

The summary checks every declared subject against its verified inventory and
requires a matching builder pass followed by an independent pass. Missing scope,
missing/mismatched pairs, invalid records or reversed order cannot produce
`visualStatus: "pass"` or advance production/runtime/release maturity, even when
the draft claims formal gates passed and no user acceptance is requested. The
rendered summary retains `requiredVisualReviews` so its coverage is inspectable.
This is evidence aggregation, not image analysis: the helper cannot discover an
omitted action, prove that a review happened, or replace detailed verdicts and
playback. `technicalStatus` still reports the draft's formal-check claim; retain
the individual technical results separately. Do not infer a whole-pet pass from
a partial review scope or use summary maturity as an execution gate.

For an older run with no scope list, retain the existing artifacts and original
verdicts. Populate the scope and compact pass records from actual matching
reviews; obtain only missing or stale reviews. Do not fabricate a review or
regenerate valid art merely to populate the summary. User acceptance remains
optional and scoped to the user's actual decision.

Do not paste complete visual-verdict objects into the run summary. The summary's
`internalVisualPasses` records use a reviewer string, whereas the standalone
verdict uses a reviewer object. For each reviewed subject, express its path
relative to the run root, copy its exact `artifactSha256`, `gate` and `verdictId`,
then record the two
actual reviews in this shape (substitute real paths, hashes, IDs and sequence
numbers; the path is relative to the run root and must be inventoried there):

```json
[
  {
    "verdictId": "identity-builder", "artifactPath": "frames/canonical.png",
    "artifactSha256": "<reviewed SHA-256>", "gate": "identity",
    "decision": "pass", "reviewer": "builder", "reviewSequence": 1
  },
  {
    "verdictId": "identity-independent", "artifactPath": "frames/canonical.png",
    "artifactSha256": "<same SHA-256>", "gate": "identity",
    "decision": "pass", "reviewer": "independent", "reviewSequence": 2
  }
]
```

`userAcceptance` is a separate record for an actual user decision, with the same
`artifactPath`, `artifactSha256` and `gate`, `decision: "pass"` for acceptance,
`reviewer: "user"`, and a later positive `reviewSequence`. Leave it empty until
that decision exists. Ordering numbers describe events; filling them in does
not create a review or approval.
Retain the standalone verdict files and their IDs as the detailed evidence.

In a standalone verdict JSON, use `decision: "pass"`, `"fail"` for a reviewed
defect, or `"needs-review"` for missing review evidence. `BLOCKED` describes the
workflow state; it is not a supported verdict `decision` value.

## Review effects and motion causally

At each visual gate, compare body occupancy independently from effect extent;
a large effect may not shrink the selected body. For ordinary locomotion, reject
a slide even if timing, bounds, and mappings pass. For a local defect, review
neighboring frames before choosing the causal repair scope. Read [Actions and
Motion](actions-and-motion.md) for what an action must communicate and [Repair
and Convergence](repair-and-convergence.md) for the minimum repair layer.

## Record the result

### Evaluate whether the skill improves actual production

When assessing a skill change, distinguish a written scenario response, a
deterministic fixture test, an inspected image/frame, a timed playback and an
observed running application. Each supports only its own claim. Two reviewers
agreeing with the instructions does not prove that generated art follows them.

Use an already-authorized representative run to check the changed decision:
retain the previous failure and its evidence, the candidate made with the
revised guidance, the unchanged task/style constraints, and any changed inputs
or generation settings. Use the same intended display size and relevant motion
cadence. Inspect the full affected artifact set and compare both improvement and
regressions; do not infer causation from one unpaired attractive output. If no
comparable earlier artifact exists, label the exercise prospective validation.

For proportion guidance, cover the selected route's neutral structure, depth
and a proportion-stressing action. Evidence from Q work does not validate the
modeled-style route or vice versa; reuse existing adequate views rather than
creating a fixed trial quota. For a narrow repair, limit this evaluation to the
affected claims and preserve unrelated passing evidence. Keep unused routes or
unavailable runtime checks explicitly unverified. Skill evaluation alone does
not authorize making a new pet, installing one, or publishing source material.

When the user requests repeated independent skill reviews, bind each round to
the same content snapshot and the requested reviewer count. Collect opinions
independently before reconciling them. Record each actionable improvement and
its disposition; after a resulting edit, reset the consecutive-pass count and
review the new snapshot. A missing review, a failed check, or an unresolved
finding does not count as a clean round. Keep this task-specific review ledger
outside the published skill; do not impose the same review quota on every pet.

### Bind the handoff evidence

Bind commands, exit codes, artifact paths/hashes, observations, blockers, and
unverified checks to the applicable verdict. The final aggregation belongs in
[Run summary](../templates/run-summary.json); status, authority, and local-state
classification remain independent from the QA verdict.
