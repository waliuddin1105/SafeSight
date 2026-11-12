---
id: adr-0005
type: decision
status: accepted
links: [datasets, training, api]
---
# Automatic source-group partitioning and HTTP boundaries

## Context
The user requested runtime dataset splitting and agreed to modularizing the backend.
This supersedes manual pre-partitioning in the initial plan.

## Options considered
Manual partitions; random frame splits; deterministic recording-group partitioning.
For HTTP: one app factory with nested handlers or resource blueprints.

## Decision
Flat manifests omit split. Validation/training create fingerprinted read-only input
copies under artifacts, assigning groups by stable seeded hash. Source IDs cannot
span groups. Legacy split datasets remain accepted. Quality gates remain intact.
Backend resource blueprints share request-local app resources; security, validation,
serialization, error handling and CLI registration have separate modules.

## Consequences
No manual split folders are required. Provenance is still required. Small datasets
may fail class/split coverage. Generated copies consume extra disk space. Stable
group IDs, seed and ratios must be shared across tasks. HTTP URLs stay unchanged;
Flask endpoint names are now blueprint-qualified. Existing worker/storage/inference
packages retain their responsibilities. No training execution is authorized.
