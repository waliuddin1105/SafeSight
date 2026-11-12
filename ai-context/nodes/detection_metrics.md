---
id: detection_metrics
type: component
status: implemented
links: [training, architecture]
---
# Detection Metrics

## What, why and how

training/common/detection_metrics.py computes per-class small/medium/large AP50 from actual boxes at native pixel scale. Empty ground-truth bins are undefined, never estimated.

## Inputs and outputs

Follow the linked component for the concrete data contract and source entrypoints.

## Gotchas

Untrained fixtures exercise software contracts; field performance requires measured held-out data.
