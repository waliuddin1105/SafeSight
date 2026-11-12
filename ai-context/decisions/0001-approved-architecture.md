---
id: adr-0001
type: decision
status: accepted
links: [architecture, dependencies, quality]
---
# ADR 0001: Approved independent-model architecture

Context: five different safety behaviors require separate datasets and checkpoints.
Options: a shared multi-task network, independent task models, or independent services.
Decision: independent models behind common adapters in one worker, Flask REST and PostgreSQL. Browser capture is required. Windows CPU is the baseline; CUDA is optional.
Consequences: fusion happens only during inference; quality must be measured at both object and event levels. No datasets are supplied, so software checks use synthetic fixtures and cannot establish accuracy.
