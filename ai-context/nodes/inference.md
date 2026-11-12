---
id: inference
type: pipeline
status: implemented
links:
- architecture
- quality
---
# Inference

## What, why and how

Artifact-specific temporal policies and thresholds feed a source-local Engine. Known negative frames count in N-of-M windows; unknown gaps expire context. Entrance classification uses the same ROI crop as collection and waits for post-crossing context.

## Inputs and outputs

Input: timestamped Prediction/Detection records. Output: deduplicated Alert records with onset, interval, actor and uncertainty.

## Gotchas

Small-object crop inference maps boxes back to the original frame. Strong fire is never suppressed; smoking-related suppression requires qualified joint context.
