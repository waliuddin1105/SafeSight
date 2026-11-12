---
id: dataset_entrance_guard
type: dataset
status: implemented
links: [datasets, entrance_guard]
---
# entrance_guard collection contract

## What and why

This dataset belongs only to entrance_guard. Classes in order: verified_entry, unverified_entry, no_entry, indeterminate.

## Inputs and outputs

The exact media/annotation/manifest layout and counts are in datasets/entrance_guard/README.md. Its independent recipe is training/entrance_guard/config.yaml. Validation writes reports outside user data.

## Gotchas

Assign source/scene/session splits before frame extraction. Retain original timestamps. Shared footage across tasks keeps its partition. User dataset contents are read-only; fixtures live under tests/fixtures.
