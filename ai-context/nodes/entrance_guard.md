---
id: entrance_guard
type: use_case
status: implemented
links:
- architecture
- quality
- dataset_entrance_guard
---
# Entrance Guard

entrance_guard is independently trainable and replaceable. Its taxonomy and collection contract are in datasets/entrance_guard/README.md; recipes and quality targets are in training/entrance_guard/config.yaml. It does not import another use-case trainer.

At runtime a crossing classified as `unverified_entry` can emit a violation. A
`verified_entry` is retained in testing output but never converted into an unverified incident;
`no_entry` and `indeterminate` do not emit violations and ambiguous crossings stay unknown.
