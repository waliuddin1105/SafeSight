---
id: video_testing
type: feature
status: implemented
links: [dashboard, api, worker, quality, adr-0010]
---
# Video, webcam and image testing workspace

## What, why and how
Authenticated users choose recorded footage, browser webcam or a still image on a dedicated
testing page. Uploaded footage/images use selected model slugs/versions and explicit evaluation
permission. Jobs snapshot their context and appear in persistent history. A still image is
validated and encoded as a one-frame MP4 so decoding/inference stays inside the worker.
Playback displays sampled boxes/scores, unknown intervals, seekable alerts, progress,
cancellation and measured processing FPS. Reloading the page retains job history.

## Inputs and outputs
Inputs: video or image, upload source, selected versions, optional capture time and annotated
event JSON; or a configured browser source and selected active model slugs. Outputs: protected ranged playback, paginated timestamped predictions,
incident timeline and optional measured event precision/recall. API contract is
docs/openapi.json; frontend API/types/auth/capture/incidents/setup/testing are separate.

## Gotchas
No supplied ground truth means no accuracy claims. Ground truth events require slug,
subtype, start/end and normalized actor box. User-supplied metrics never qualify a
production model. Unknown or absent results do not mean safe footage. The observation
list retains a bounded 5000-row display window; paginated API results remain available.
Entrance verification is disabled for still images because it requires an ordered sequence.
Single-image jobs expose detections/classifications but cannot establish persistence-based alerts.
Webcam model selection applies to that source session and does not select inactive versions.
