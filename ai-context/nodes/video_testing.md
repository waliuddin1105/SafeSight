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
Playback displays sampled boxes with an attached class/confidence badge, unknown intervals,
seekable alerts, progress, cancellation and measured processing FPS. Bright, lightly tinted box
outlines remain distinct from their dark badge backgrounds. Badges sit outside small detections
so they do not hide the detected region; labels for large edge-touching regions stay inside the
frame. A resize-aware collision layout measures the player, reserves each badge footprint and
uses the nearest free position above, below or beside its box. Colors are stable by class and the
HTML overlay keeps text readable without stretching across video aspect ratios. Reloading the
page retains job history.

Normal overlays apply the model card's display floor (default 0.10). Reviewers can explicitly
show retained low-confidence candidates down to the inference floor without changing fusion,
temporal state, incidents, or qualification metrics.

## Inputs and outputs
Inputs: video or image, selected versions, optional capture time and annotated event JSON;
or a configured browser source and selected active model slugs. Uploads automatically use a
neutral backend-managed Testing Lab source/location unless an API client explicitly supplies a
configured source. Outputs: protected ranged playback, paginated timestamped predictions,
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
The ordinary testing UI intentionally has no location/source selector; location-specific policy
testing remains available to API clients through the optional source_id field.
