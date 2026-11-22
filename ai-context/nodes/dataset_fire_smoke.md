---
id: dataset_fire_smoke
type: dataset
status: implemented
links: [datasets, fire_smoke]
---
# fire_smoke collection contract

## What and why

This dataset belongs only to fire_smoke. Classes in order: smoke, fire. Person context is
supplied by the pose context asset and other tasks' detections at inference time.

## Inputs and outputs

The exact media/annotation/manifest layout and counts are in datasets/fire_smoke/README.md. Its independent recipe is training/fire_smoke/config.yaml. Validation writes reports outside user data.

`tools/prepare_fire_smoke_corpus.py` acquires pinned D-Fire and strict-validated
FireViewer/FASDD sources, verifies SHA-256 hashes, converts them to `smoke=0, fire=1`,
removes exact duplicates and publishes an unsplit manifest. FireViewer scene groups are
retained. D-Fire is conservatively grouped by its AoF, WEB and PublicDataset families.
Downloads are resumable; the manifest is published only after the corpus is complete.
When reconstructing YOLO box edges, validation allows `1e-6` of decimal serialization
tolerance at image boundaries. Materially out-of-frame boxes still fail validation.

## Gotchas

Assign source/scene/session splits before frame extraction. Retain original timestamps. Shared footage across tasks keeps its partition. User dataset contents are read-only; fixtures live under tests/fixtures.
The combined public image corpus can train the detector but cannot qualify temporal alerts;
that still requires independently annotated validation/test recordings.
