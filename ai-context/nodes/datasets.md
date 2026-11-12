---
id: datasets
type: dataset
status: implemented
links:
- adr-0008
- adr-0005
- architecture
- quality
- dataset_sourcing
- dataset_preparation
---
# Datasets

Read-only datasets use source/session grouped splits. Manifests prove provenance; video event labels support alert evaluation. Generated fixtures live only in tests/fixtures.

## Implementation progress

Implemented contracts, read-only validation, synthetic fixtures and 11 regression checks. Checks cover corrupt labels/media, missing labels, provenance leakage, exact duplicates and graph orphans.

Flat inputs now omit split. Validation/training stage reproducible group-based partitions under artifacts; see docs/AUTOMATIC_SPLITS.md and ADR 0005. Legacy layouts remain accepted.

Image training and frozen qualification are separate commands; see docs/IMPROVEMENTS.md and ADR 0008.
