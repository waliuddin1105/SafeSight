---
id: dataset_phone_usage
type: dataset
status: implemented
links: [datasets, phone_usage]
---
# phone_usage collection contract

## What and why

This dataset belongs only to phone_usage. Classes in order: person, phone.

## Inputs and outputs

The exact media/annotation/manifest layout and counts are in datasets/phone_usage/README.md. Its independent recipe is training/phone_usage/config.yaml. Validation writes reports outside user data.

## Gotchas

Assign source/scene/session splits before frame extraction. Retain original timestamps. Shared footage across tasks keeps its partition. User dataset contents are read-only; fixtures live under tests/fixtures.
