---
id: adr-0006
type: decision
status: accepted
links: [training, artifacts, dependencies]
---
# Colocated recipes and shared-drive model transfer

## Context
The user authorized the recommended structure improvements. Trainers need easily
discoverable independent recipes, and three contributors need model sharing.

## Options considered
Central training configs versus colocated configs; Git LFS, DVC, or a shared drive.

## Decision
Move recipes to training/SLUG/config.yaml, updating defaults, tooling and documentation.
Use shared-drive ZIP bundles and a checksum-verified export/fetch CLI. No automated
upload or account setup is implied. Version import never changes active model cards.
Keep existing inference/ingestion/worker/contracts packages and the implemented CI.
Remove known generated root settings and empty legacy dataset partitions only.

## Consequences
Explicit old config paths must be updated. Model binaries remain ignored. Immutable
versions can be transferred without changing quality metadata or bypassing activation.
Context pretrained assets and joint fusion qualification remain separate prerequisites.
