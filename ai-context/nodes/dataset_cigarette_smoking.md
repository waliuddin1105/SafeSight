---
id: dataset_cigarette_smoking
type: dataset
status: implemented
links: [datasets, cigarette_smoking]
---
# cigarette_smoking collection contract

## What and why

This dataset belongs only to cigarette_smoking. Classes in order: person, cigarette, lighter, smoke.

## Inputs and outputs

The exact media/annotation/manifest layout and counts are in datasets/cigarette_smoking/README.md. Its independent recipe is training/cigarette_smoking/config.yaml. Validation writes reports outside user data.

## Gotchas

Assign source/scene/session splits before frame extraction. Retain original timestamps. Shared footage across tasks keeps its partition. User dataset contents are read-only; fixtures live under tests/fixtures.
