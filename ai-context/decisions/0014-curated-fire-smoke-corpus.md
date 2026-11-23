---
id: adr-0014
type: decision
status: accepted
links: [dataset_fire_smoke, fire_smoke, quality]
---
# ADR 0014: curate multi-source fire/smoke data before retraining

## Context

The D-Fire-trained detector performs poorly on aerial, obscured and industrial fire. The local
remote-sensing subset has no fire labels, and its validation audit reports suspected cross-split
near duplicates. Blindly merging public exports would amplify inconsistent labels and duplicates.

## Options considered

- Continue training on D-Fire only.
- Merge every publisher export without filtering.
- Build a provenance-preserving curated corpus and quarantine uncertain records.

## Decision

Use pinned unaugmented exports, confirmed-perceptual deduplication, strict two-class normalization,
source/scene grouping and explicit quarantine. Keep a balanced D-Fire replay subset. All visible
fire is detector ground truth; location policy decides whether it is a violation. Publisher
`other` annotations provide negative context. Target-video prelabels require human review.

## Consequences

Preparation is reproducible, but automated validation cannot certify every semantic boundary.
Missing credentials or unresolved review items prevent affected data from entering the corpus.
