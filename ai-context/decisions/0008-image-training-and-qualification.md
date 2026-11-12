---
id: adr-0008
type: decision
status: accepted
links: [training, datasets, quality, verification]
---
# Image training and frozen alert qualification

## Context
The user approved P1-P8 and confirmed four use cases train on images.

## Decision
Training validates image/clip labels and provenance, fits on train and selects on
validation only. It exports an evaluation-only version. tools/qualify_model.py loads
that frozen version, requires full event evaluation inputs and measures test data once.
Qualification fingerprints are distinct from training data. No trainer is executed
during implementation. Frozen features are checksum-verified disk datasets, staging
names use sample identity, and accumulation accounts for actual final group size.

## Consequences
Image-only datasets can train without alert footage. Guard still requires ordered
clips. Missing event evidence blocks qualification, never silently grants PASS.
Source-group assignment stays deterministic across revisions. Existing quality
targets, source isolation and unqualified artifact safeguards remain.
