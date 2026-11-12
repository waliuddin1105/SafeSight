---
id: release_checks
type: component
status: implemented
links: [adr-0007, verification, architecture]
---
# Release Checks

## What, why and how

tools/check_release.py checks source syntax/import isolation, pin consistency, collection contracts, context reachability and Compose structure without importing a trainer. CI uses untrained inference fixtures and has no training step.

## Inputs and outputs

Follow the linked component for the concrete data contract and source entrypoints.

## Gotchas

Untrained fixtures exercise software contracts; field performance requires measured held-out data.

Hosted-DB Compose contract rejects DATABASE_URL overrides and no longer requires a bundled db service.
