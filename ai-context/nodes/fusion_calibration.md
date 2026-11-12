---
id: fusion_calibration
type: pipeline
status: implemented
links: [quality, architecture]
---
# Fusion Calibration

## What, why and how

tools/evaluate_fusion.py calibrates the installed smoking/fire pair on joint validation footage, freezes thresholds, then evaluates untouched test footage. fusion_card.json binds thresholds/policy to exact model card hashes. Without a matching PASS, runtime keeps smoke unresolved.

## Inputs and outputs

Follow the linked component for the concrete data contract and source entrypoints.

## Gotchas

Untrained fixtures exercise software contracts; field performance requires measured held-out data.
