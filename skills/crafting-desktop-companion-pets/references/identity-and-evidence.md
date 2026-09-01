# Identity and Evidence

Read this for a new pet, identity/proportion repair, reference selection, or an
evidence conflict. Read [Canonical Identity and
Proportions](canonical-identity-and-proportions.md) when this evidence must
select or repair a canonical identity.

## Choose the route

- **Source-faithful:** current official target evidence governs identity.
  Historical material from the same character can supply compatible motion
  grammar, but cannot restore an older face, costume, palette, ability, or
  power level.
- **Original/brand:** an approved creative brief governs identity and
  proportion. Brand cues remain abstract unless the user supplied and
  authorized the exact protected assets.

Creation, research, or a selected reference does not grant installation,
integration, commit, push, publication, account use, or global configuration.
Record each authority separately in the project record.

## Record the evidence ledger

For every source, record the exact target or claim, source and locator,
artifact path/hash when available, evidence class, role or roles, allowed use,
conflict, effect caster/ownership when relevant, named uncertainty, provenance
status, and independent selection. The machine-readable source record uses
`id`, `roles`, `allowedUses`, and `evidenceClass`; a project-defined source
also records `approvedFor` when an approval grants a role. Use
[Evidence ledger](../templates/evidence-ledger.md) for the human record and
[Identity contract](../templates/identity-contract.json) for the selected
identity state.

When the user authorizes source acquisition, online evidence may be downloaded
or captured inside the bounded local run root and used in this same evidence
workflow. Preserve its original source/locator and record the local artifact
path/hash; local storage alone does not change its evidence class, roles,
allowed uses, provenance, selection, approval, or authority.

Provenance is one of `REQUIRED`, `DERIVED`, `PROPOSED`, or `APPROVED`.
Selection is independently `candidate` or `selected`; an autonomously selected
proposal remains `PROPOSED`, not `APPROVED`.

## Reference roles

| Role | May govern |
|---|---|
| `identity` | face, age impression, hair, marks, and other recognizable traits |
| `proportion` | target-specific silhouette, body relationships, and body occupancy |
| `costume` | cut, layers, palette, and patterns |
| `motion` | compatible pose, phase, garment, or prop motion |
| `effect` | caster, origin, travel, peak, decay, and cleanup |
| `style` | line, material, rendering, or simplification treatment |
| `desktop-calibration` | actual-size readability and desktop-use observations |
| `layout-only` | cell count, order, placement, and safety margins |
| `prohibited` | material excluded from the stated derivation |

A reference grants only its recorded roles. Style, calibration, motion, effect,
or layout never silently grants identity or proportion authority. A
user-requested cross-character width or geometry number is only a
hypothesis/calibration request; it does not gain proportion authority or become
`REQUIRED` for the target without independent target-specific evidence or an
approved target design.

## Validate role authority

For identity or proportion, use `current-official`,
`same-character-current`, `approved-original-design`, or a project-defined
source whose `approvedFor` explicitly contains that role. The deterministic
validator reports these relevant codes:

| Code | Meaning and next action |
|---|---|
| `ROLE_IDENTITY_UNSUPPORTED` | Replace or explicitly approve the identity evidence; do not select from the source. |
| `ROLE_PROPORTION_UNSUPPORTED` | Replace or explicitly approve target-specific proportion evidence; calibration alone is insufficient. |
| `PROHIBITED_REFERENCE_HAS_ALLOWED_USE` | Remove the allowed use or remove the `prohibited` role before use. |
| `REFERENCE_ID_INVALID`, `REFERENCE_ROLES_INVALID`, `REFERENCE_ALLOWED_USES_INVALID`, `REFERENCE_EVIDENCE_CLASS_INVALID`, `REFERENCE_APPROVED_FOR_INVALID` | Repair the malformed ledger record before evaluating authority. |
| `IDENTITY_ROUTE_INVALID` | Choose `source-faithful` or `original-brand` before evaluation. |

For source-faithful work, selection needs supported identity and proportion
evidence unless the identity contract records the named uncertainty and its
approval. For original/brand work, selection needs an approved original design
brief; it does not need official media. The identity gate owns the resulting
`SOURCE_FAITHFUL_IDENTITY_REQUIRED`, `SOURCE_FAITHFUL_PROPORTION_REQUIRED`,
and `APPROVED_CREATIVE_BRIEF_REQUIRED` blockers.

## Resolve conflict and uncertainty

Current official identity outranks historical identity. Keep high-salience
selection provisional when the target’s silhouette, face/age/mark, dominant
costume blocks, or signature hair/ornaments lack direct or corroborated
evidence. Record the uncertainty by name and stop at the earliest affected
gate unless the user explicitly approves that uncertainty.

For mixed battle footage, record an effect whitelist and blacklist. “Fits the
setting” is not caster ownership evidence. Read [Actions and
Motion](actions-and-motion.md) for the lifecycle after ownership is established.

## Handoff to the identity gate

The selected evidence IDs, canonical artifact/hash, technical evidence, and
actual-size visual verdict must agree. A technical diagnostic can never grant a
visual pass; read [Canonical Identity and
Proportions](canonical-identity-and-proportions.md) for the state machine and
[Visual QA](visual-qa.md) for review evidence. The [Nangong Wan Calibration
Case](nangong-wan-calibration-case.md) is process-only calibration, not another
target’s identity or proportion source.
