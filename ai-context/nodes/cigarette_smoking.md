---
id: cigarette_smoking
type: use_case
status: implemented
links:
- architecture
- quality
- dataset_cigarette_smoking
---
# Cigarette Smoking

cigarette_smoking is independently trainable and replaceable. Its taxonomy and collection contract are in datasets/cigarette_smoking/README.md; recipes and quality targets are in training/cigarette_smoking/config.yaml. It does not import another use-case trainer.

Imported evaluation candidates may contain a nonempty subset of the canonical classes. The
`imported-cigarette-v1` candidate supports only visible cigarette boxes; it has no person,
lighter, or smoke detector outputs and is unqualified. The inference context can still associate
visible cigarette boxes with pose tracks, while hidden-smoking cues requiring missing detector
classes remain unavailable. The canonical trained model contract remains unchanged.
