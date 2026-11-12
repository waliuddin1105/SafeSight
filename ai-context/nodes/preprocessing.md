---
id: preprocessing
type: component
status: implemented
links: [inference, architecture]
---
# Preprocessing

## What, why and how

entrance_frame performs normalized xyxy crop then aspect-preserving resize. Training, cached evaluation and runtime share it. Source config uses entrance_roi; clip annotations use roi. Body normalization travels inside its exported module.

## Inputs and outputs

Follow the linked component for the concrete data contract and source entrypoints.

## Gotchas

Untrained fixtures exercise software contracts; field performance requires measured held-out data.
