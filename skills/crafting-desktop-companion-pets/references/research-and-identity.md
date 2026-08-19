# Research and Identity

## Evidence ledger and production boundary

Create an evidence ledger before visual production. For each fact, record source, observed detail, allowed use, provenance status, `selection: candidate|selected`, and uncertainty. User screenshots and researched animation establish identity or action evidence; they are not automatically reusable sprite assets. Produce original assets unless the user supplies an approved asset or grants reuse rights.

## Research sufficiency and version recommendation

Do not ask the user to remember every source detail before research. Actively inventory distinctive forms, transformations, locomotion, interactions, gaze, props, layered or wide effects, quality variants, multi-step sequences, restoration boundaries, and relative autonomous behavior that could affect v2/v3/v4.

A version recommendation is ready when:

- source behaviors likely to affect the format have representative evidence;
- observed facts, plausible but unverified traits, and absent traits are distinguished;
- remaining uncertainty that could change the route is either resolved through accessible research or presented as an explicit alternative;
- viable formats can be compared by preserved fidelity, omissions, production complexity, and extensibility.

Recommend the version that best preserves the intended source fidelity, then ask the user to confirm it. Record the chosen route in `FORMAT_CONFIRMATION`; do not convert the preliminary action/form inventory into final contracts or batch assets until confirmation. A version preference stated before the research-backed recommendation remains evidence and must be reconfirmed afterward.

Use the identity master as the source of truth for silhouette, face, proportion, hair, costume layers, palette, asymmetry, props, and form-specific differences. `APPROVED` means recorded user or governing-artifact approval. For an authorized creation request, an agent-self-reviewed `PROPOSED` master with `selection: selected` that passes applicable identity and visual gates may proceed to a full action family without user approval. Missing user approval blocks only when the request explicitly requires it or an unresolved subjective ambiguity has no safe evidence-based resolution.

## Proportion routes

| Requested route | Source rule |
|---|---|
| Slender | Preserve the supplied slender reference's body ratio and silhouette. |
| Chibi | Use an approved existing chibi reference only when the user requests chibi proportions. |
| Unspecified | Record the choice as `PROPOSED` with `selection: candidate`; do not infer it from a neighboring pet. |

## Target isolation and contracts

For an existing package, use only its manifest, mapped assets, approved references, and explicitly linked evidence. Keep an immutable comparison set for unrelated assets. Never infer its character, version, frame count, anchors, dimensions, tooling, or destination from a nearby package.

Create an action/form contract before batch work. Include identity master, each form, action role/direction, start and end pose, screen/world anchor or footline, prop/hand/occlusion requirements, menu/autoplay/runtime semantics, acceptance checks, evidence source, one provenance status (`REQUIRED`, `DERIVED`, `PROPOSED`, or `APPROVED`), and `selection: candidate|selected`.

| Decision kind | Correct status |
|---|---|
| Runtime requirement or explicit user constraint | `REQUIRED` |
| Atlas bounds or anchor calculated from recorded master/layers | `DERIVED` |
| Agent-originated creative pose, timing, weight, ID, path, or form lacking recorded user/governing approval | `PROPOSED` |
| User-approved or governing-artifact-approved source value | `APPROVED` |

`candidate` is not yet chosen. `selected` passed applicable self-review and may be used in an authorized completed package; it does not change a `PROPOSED` value into `APPROVED`. For v4, maintain a per-form identity matrix: form silhouette, palette/costume/prop changes, required idle/moves/interactions, representative action, default-only gaze, entry/resident/exit continuity, and full/simplified body-anchor expectations. Each entry retains its provenance status, selection, and source.
