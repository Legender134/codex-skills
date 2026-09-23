# Execution, model capabilities, and resuming work

Use the project's configured roles; model preferences are not runtime evidence.
Record the actual model/effort if the host exposes them, otherwise unknown.
Changing a file does not change a running task. Retain existing provider, billing
and concurrency boundaries. Do not default every job to maximal effort.

## Image tooling (verified 2026-09-20)

Built-in image generation remains the default. Its live schema determines which
controls exist. If it exposes only a prompt and reference images, request the
desired properties in the prompt and validate the returned image; do not claim
hard size, quality or model control. Store requested and observed values separately.

For an explicitly authorized API route, Image 2.5 Flare is a candidate for quick
exploration; Sunburst is a candidate for identity-preserving edits and final art.
Compare the same inputs before changing a production baseline. Neither model
guarantees exact proportions, animation continuity or alpha quality.

| Image 2.5 API control | Supported values / limits |
| --- | --- |
| Models | `gpt-image-2.5-sunburst`, `gpt-image-2.5-flare`; both have `2026-09-08` snapshots |
| Quality | `low`, `medium`, `high`, `xhigh`, `max`, `auto` |
| Transparency | `background=transparent` with PNG or WebP; validate actual alpha |
| Size | `auto`, or both edges divisible by 16, max edge 3840, ratio at most 3:1, 655360–8294400 total pixels |

For a new workflow without an established baseline, 1024x1024 and medium quality
can be an exploratory starting point when the composition fits. For a migration
or model comparison, preserve the baseline prompt, references, output dimensions,
format and explicitly selected quality when both models support them. Record any
necessary parameter incompatibility; do not silently reset the baseline. Change
one setting at a time in response to an unmet acceptance criterion, and measure
quality and latency before adopting the change. Outputs above 3,686,400 total pixels
(2560x1440) are experimental, not a default production target.
Do not send runtime-cell sizes such as 192x208 to the API: generate within its
limits, then deterministically register the result.
Image 2 transparency is now in preview; older blanket rejection of transparency
is not a reason to silently downgrade models. Preserve explicitly selected models
and their own limits. An older local CLI may reject newer controls: inspect its
version/help and perform an authorized compatibility update before using it.
This skill does not replace the host's bundled imagegen skill or authorize API use.

Sources: [image generation](https://developers.openai.com/api/docs/guides/image-generation),
[image prompting and migration](https://developers.openai.com/api/docs/guides/image-prompting),
[Sunburst](https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst),
[Flare](https://developers.openai.com/api/docs/models/gpt-image-2.5-flare),
[Astra guidance](https://developers.openai.com/api/docs/guides/latest-model).

## Resume and approvals

Keep one lightweight project state record. New runs created with
`prepare_pet_run.py` include [production-state.json](../templates/production-state.json).
If an existing project already has a state record, retain it instead of creating
a competing source of truth. Record approved decisions and their evidence,
separate authority, actual tool metadata, current phase, blockers, and next action.
Reference detailed contracts, source hashes, jobs and reviews instead of duplicating
them. State is an index, not an alternative validator or a self-awarded gate pass.
Recheck the affected contracts and hashes before resuming dependent work.

Do not repeat approvals for the same style, scope or local production authority.
When internal gates pass, continue already-authorized work. Ask only for an
irreducible design choice, explicit user-reserved acceptance, or additional authority.
Do not equate advance production approval with acceptance of an unseen image.

Arrange independent review through an available read-only role before it is needed;
one reviewer can review a coherent batch. Preserve all-frame coverage and hash binding.
Record the actual role used, not just the configured preference. If unavailable,
block dependent claims and continue useful independent work. Never ask the user to
replace internal QA.

Before each generation, save the exact prompt, reference roles/hashes and expected
output. Afterward save the returned path/hash and observed dimensions/alpha/model.
Limit retries per risk pilot and repair root causes; do not regenerate a whole pack
because a single action failed. Existing passing pilots are production assets when
promoted, not automatic invitations to regenerate them.
