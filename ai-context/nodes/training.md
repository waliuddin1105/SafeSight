---
id: training
type: pipeline
status: implemented
links:
- adr-0009
- adr-0008
- adr-0006
- adr-0005
- architecture
- quality
---
# Training

## What, why and how

Independent YAML entrypoints validate before fitting, seed RNGs, support resume, early-stop and export versioned artifacts. No entrypoint was executed in this completion pass.

## Inputs and outputs

Input: each task dataset and training/<slug>/config.yaml. Output: checkpoints, measured validation/test reports and models/<slug>/versions/<run>.

## Gotchas

Calibration requires adequate validation support. Test is held out until all choices are frozen. Classifier checkpoints replace atomically; source and preprocessing asset identities are recorded.

Before validation, materialize_splits creates or verifies fingerprinted source-group partitions. Seed/ratios and source provenance are explicit; originals are unchanged.

Recipes are colocated at training/<slug>/config.yaml; old configs/training paths were removed.

Image training and frozen qualification are separate commands; see docs/IMPROVEMENTS.md and ADR 0008.

Validation-only comparison and measured failure galleries are implemented; see ADR 0009.

Checkpoint restoration is shared by resume and OOM rollback and tested with inert state objects. Qualification uses the frozen card policy and receiving model-root assets. Optional recipes travel with model bundles.
