# Project brief (draft)

## Project identity

- Project ID:
- Identity route: `source-faithful` or `original-brand`
- Requested format route: `undecided`, `v2`, `v3`, or `v4`
- Requested task type:

## Capability decision record

For a new package or migration, research the current runtime capabilities
before locking the route. Record the capability matrix:

| Required capability / evidence | Required? | v2 | v3 | v4 | Route-changing uncertainty |
|---|---|---|---|---|---|
| Forms/transformations | | | | | |
| Dynamic actions/timing | | | | | |
| Wide/layered effects | | | | | |
| Gaze | | | | | |
| Sequences/restoration | | | | | |
| Autoplay grouping | | | | | |

- Required capabilities and evidence:
- Alternatives considered:
- Fidelity preserved:
- Fidelity omitted by each alternative:
- Limitations:
- Complexity/extensibility:
- Route-changing uncertainty:
- Explicit post-research confirmation:

Use the version references for current runtime capability authority. This human
decision record does not define package or manifest JSON fields. Do not lock the
schema, atlas/layer architecture, final action contract, or batch production
before the explicit post-research confirmation.

## Authorization

- Identity uncertainty approval:
- Installation authority: no
- Integration authority: no
- Commit authority: no
- Push authority: no
- Publication authority: no

## Source roles

Record each source and the role it is allowed to govern: identity,
proportion, costume, motion, effect, style, desktop calibration,
layout-only, or prohibited.

## Unresolved uncertainty

-

## Next gate

State the earliest applicable gate and the evidence or approval needed to
enter it. Empty evidence does not pass a gate.

## Scheduler and interruption contract

Record menu and autoplay eligibility independently. Autoplay pool, weight,
cooldown, shared group, repeat limit, priority, environmental conditions,
interruption, recovery, direction, distance basis, boundary policy, and any
runtime limitation must be evidenced separately. An iconic action may remain
manual-eligible while being rare in autoplay; a weight alone does not predict
observed frequency.

For movement, record world-motion phases, direction, a usable-screen-relative
fraction or runtime-derived formula with SHA-256 evidence, edge policy, safe
interruption phase, and recovery. For a large effect, record a positive
cooldown/shared group or a hash-bound explanation of why the runtime route
cannot expose either control.

## Maturity and authorities

Keep these maturity stages in order: `research-candidate`,
`identity-candidate`, `identity-selected`, `storyboard-candidate`,
`production-frames`, `runtime-valid`, `installed-test`,
`long-use-candidate`, and `release-candidate`.

Package/schema checks, visual review, runtime Registry/Catalog evidence,
installation evidence, soak results, user acceptance, and authorization are
separate. User acceptance must name the reviewed artifact, SHA-256, gate,
decision, and reviewer; it never grants installation, integration, commit,
push, or publication authority. Record the required/observed soak duration and
verdict. Do not treat a package pass as runtime evidence or evidence as
authority.

## Run-summary publication

Keep the generated run summary outside the run root. Inventory and hash each
input from one protected handle, then recheck the same inputs immediately before
publication. The output path is immutable: an absent output may be created with
an atomic no-replace operation; a byte-identical existing output is a no-write
success; a different or aliased output is a failure. Do not use publication to
move, delete, rename, or rewrite any run input, and treat any post-commit path
or close uncertainty as a diagnostic rather than an unchanged-output result.

Protected reads must preserve input and existing-output bytes and metadata,
including access, write, and change times. On Windows, use a same-handle
`FileBasicInfo` sentinel to suppress all I/O-updated timestamps before reading;
on POSIX, require both `O_NOFOLLOW` and `O_NOATIME` for every regular read. If
either route cannot prove that property, fail closed before reading; never
repair timestamps through a pathname.

On POSIX, retain an unnamed `O_TMPFILE` object through publication. Use
descriptor-bound `linkat(AT_EMPTY_PATH)` first; only when the capability-bound
route is unavailable may it retry through that same live descriptor's
`/proc/self/fd/<fd>` reference with `AT_SYMLINK_FOLLOW`, still targeting the
held parent descriptor without replacement. Missing either safe route is a
controlled failure, never a pathname-based temporary fallback.
