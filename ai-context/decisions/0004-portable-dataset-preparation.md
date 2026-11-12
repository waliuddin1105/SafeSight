---
id: adr-0004
type: decision
status: accepted
links: [dataset_preparation, dataset_sourcing, quality]
---
# ADR 0004: Portable acquisition with explicit annotation readiness

## Context

The user will train on another computer and requested one preparation script. The
shortlisted datasets have annotation and provenance gaps relative to the approved
schema. Their names and sizes cannot establish an 80% performance claim.

## Options

Weaken class/event requirements, generate automatic labels, or preserve strict dataset
contracts while automating acquisition and importing complete reviewed bundles.

## Decision

Keep the approved classes, source-group split requirements and quality targets. Provide
a configurable cross-device downloader/extractor, provider credentials through .env,
local archive support and non-overwriting installation for validated native bundles.
Incomplete public exports are retained as original sources and explicitly reported as
needing annotations. No model training, pseudo-labeling or local bulk download occurs.

## Consequences

The storage destination is chosen on the future training device. Downloading four
archives cannot make the current sources fully train-ready without missing annotations.
The script clearly separates download success, structural readiness and model quality.
This extends the original empty-dataset assumption under the user's explicit request,
while preserving existing data and the no-training instruction.
