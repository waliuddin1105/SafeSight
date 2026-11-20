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

## Gotchas

Assign source/scene/session splits before frame extraction. Retain original timestamps. Shared footage across tasks keeps its partition. User dataset contents are read-only; fixtures live under tests/fixtures.
