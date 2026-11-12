---
id: dataset_sourcing
type: dataset
status: researching
links: [datasets, quality]
---
# Public dataset sourcing

## What and why

The user requested annotated public data for all tasks except entrance_guard. This
authorizes sourcing new data despite the original empty-dataset assumption. Training
remains prohibited. Existing user data must be preserved.

## Inputs and outputs

Primary-source candidates, annotation mismatches and access observations are recorded
in docs/DATASET_SOURCES.md. No data is installed yet. Acquisition now runs on the future training device through tools/prepare_datasets.py.
The approved taxonomy and strict readiness requirements are retained.

## Gotchas

Local disk limitations do not prevent preparing the acquisition script for another device. Static image
annotations cannot establish temporal event accuracy. Never invent source groups,
replace head boxes with person boxes, or present draft labels as verified ground truth.
