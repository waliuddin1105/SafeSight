---
id: dataset_preparation
type: pipeline
status: implemented
links: [adr-0005, datasets, dataset_sourcing, training, quality, adr-0004]
---
# Cross-device dataset preparation

## What, why and how

tools/prepare_datasets.py runs on the eventual Python 3.11 training computer. It
selects one/all four non-guard tasks from configs/dataset_sources.yaml, resolves
public/authenticated exports, resumes compatible HTTP downloads, records hashes and
safely extracts ZIP/TAR into each task's _sources directory. Existing user data is
preserved. No training or model inference is performed.

## Inputs and outputs

Inputs: provider access through .env, configured sources or local --archive entries,
--datasets-root/--cache-root and optionally reviewed native dataset bundles.
Outputs: original annotations, preparation.json/inventory per task, a summary report,
and a generated training configuration only when a complete native bundle validates.
--plan performs no network access or dataset writes. Default selection excludes guard.

## Gotchas

DOWNLOADED_NEEDS_ANNOTATIONS is not READY. Head boxes are not person boxes; absent
lighter/person/event annotations are not synthesized. No frame-random splitting is
performed. READY indicates structural training compatibility, never measured accuracy.
Public sources/authentication have not been downloaded end to end on this PC; tests
use synthetic local archives and HTTP only. See docs/DATASET_PREPARATION.md.
The 18 preparation tests and all 42 unit tests pass on Windows; no trainer was run.
Cross-platform execution and real-data quality remain unverified.

Reviewed native bundles may be flat: readiness validation materializes group splits before applying the unchanged dataset contract.
