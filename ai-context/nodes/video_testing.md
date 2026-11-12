---
id: video_testing
type: feature
status: implemented
links: [dashboard, api, worker, quality, adr-0010]
---
# Recorded-video testing workspace

## What, why and how
Authenticated users upload footage with selected model slugs/versions and explicit
evaluation permission. Jobs snapshot their context and appear in persistent history.
Playback displays sampled boxes/scores, unknown intervals, seekable alerts, progress,
cancellation and measured processing FPS. Reloading the page retains job history.

## Inputs and outputs
Inputs: video, upload source, selected versions, optional capture time and annotated
event JSON. Outputs: protected ranged playback, paginated timestamped predictions,
incident timeline and optional measured event precision/recall. API contract is
docs/openapi.json; frontend API/types/auth/capture/incidents/setup/testing are separate.

## Gotchas
No supplied ground truth means no accuracy claims. Ground truth events require slug,
subtype, start/end and normalized actor box. User-supplied metrics never qualify a
production model. Unknown or absent results do not mean safe footage. The observation
list retains a bounded 5000-row display window; paginated API results remain available.
