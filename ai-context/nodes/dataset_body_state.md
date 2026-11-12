---
id: dataset_body_state
type: dataset
status: implemented
links: [datasets, body_state]
---
# body_state collection contract

## What and why

This dataset belongs only to body_state. Classes in order: upright, seated, crouching_kneeling, deep_bend, lying_on_floor.

## Inputs and outputs

The exact media/annotation/manifest layout and counts are in datasets/body_state/README.md. Its independent recipe is training/body_state/config.yaml. Validation writes reports outside user data.

## Gotchas

Assign source/scene/session splits before frame extraction. Retain original timestamps. Shared footage across tasks keeps its partition. User dataset contents are read-only; fixtures live under tests/fixtures.
