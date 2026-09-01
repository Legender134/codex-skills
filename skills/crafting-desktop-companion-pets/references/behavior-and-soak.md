# Behavior and Soak

Read this for scheduler, movement, interruption, runtime behavior, or long-use
review. It owns target-specific behavior policy and the soak/stop decision;
[Visual QA](visual-qa.md) owns the associated gate evidence.

## Record behavior independently

For every action, record manual eligibility, autoplay eligibility, pool, weight,
cooldown, shared group, repeat limit, priority, environmental conditions,
interruption, recovery, and route-specific scheduler limitation. Manual access
and autoplay frequency are independent: an iconic action can be manual-eligible
and rare automatically. A weight alone never predicts observed frequency because
eligibility, pool selection, cooldown, duration, conditions, and runtime
scheduling also apply.

For a stable weighted pool, record the oracle and method before testing. Use at
least five deterministic seeds and enough eligible choices for the
lowest-probability candidate to have at least 100 expected selections. The
default static-pool check is Pearson multinomial goodness-of-fit at
`alpha=0.01` plus Bonferroni-adjusted two-sided 99% binomial intervals.

For a cooldown, priority, or other stateful scheduler, use the executable
scheduler specification or governing tests. If no defensible expected
distribution exists, verify reachability, cooldown, anti-streak, and starvation
invariants and mark the distribution `UNVERIFIED` instead of inventing fairness
from weights. Real-use soak evaluates perceptual dominance and experience, not
statistical fairness.

## Specify movement and bounds

Separate ordinary movement from exceptional travel. A movement action records
direction, declared world-motion phases, a usable-screen-relative distance or
recorded runtime-derived formula, boundary policy, safe interruption phase, and
recovery. Verify effective distance, inward edge selection or clamped target,
multi-display and DPI behavior, interruption landing point, and return. Do not
replace movement acting with a shifted standing frame.

For a large effect, record a cooldown/shared group or evidence that the selected
runtime route cannot expose either control. Do not derive weights, cooldowns,
distances, or action counts from the [Nangong Wan Calibration
Case](nangong-wan-calibration-case.md).

## Soak at normal desktop scale

After applicable visual and runtime gates pass, soak at the change’s risk level.
A full new pet normally needs 30–60 minutes; a local deterministic repair reruns
only affected experience. Record duration required/observed, build and artifact
hashes, settings, event counts, backgrounds, displays/DPI, repetition,
dominance, absent actions, invisible rarity, edge behavior, interruption,
recovery, resources, and logs in [Run summary](../templates/run-summary.json).

## Stop rule

Stop adding content when identity, coverage, visual, runtime, behavior, and
applicable long-use gates pass. “More actions are possible” is not evidence of
improvement. If the soak reveals a defect, return to the causal layer using
[Repair and Convergence](repair-and-convergence.md).
