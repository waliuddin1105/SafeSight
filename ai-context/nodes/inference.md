---
id: inference
type: pipeline
status: implemented
links:
- adr-0010
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

YOLO inference applies class-aware NMS followed by containment-aware deduplication. The highest-confidence box is retained when same-class boxes substantially overlap or one is nested inside another. Overlap between different classes, such as fire inside smoke, is deliberately preserved. Model cards may override `postprocessing.nms_iou` and `postprocessing.containment_threshold`; defaults are 0.45 and 0.8.

Registry can load explicit pinned cards and reuse compatible global adapters/pose without duplicating weights. Full-frame/crop and temporal settings remain versioned.
