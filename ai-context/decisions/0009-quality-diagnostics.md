---
id: adr-0009
type: decision
status: accepted
links: [training, detection_metrics, quality]
---
# Validation comparisons and measured failure evidence

## Context
P3 requires actionable reports without estimating accuracy from dataset counts.

## Decision
Store immutable training-validation reports alongside qualification reports. Compare
real runs only when their training dataset fingerprints match. Fallback recipes are
written explicitly and never executed automatically. Event replay records measured
false-positive/negative examples and emits a bounded, escaped HTML thumbnail gallery.
Dataset inventory counts source groups, classes and tiny objects; pose failures are
reported before fitting. Suspected annotation noise stays a hypothesis.

## Consequences
Model-level and deployed-pipeline metrics are explicitly labeled. Reviews never become
ground truth automatically. No report or comparison runs a trainer or relaxes quality gates.
