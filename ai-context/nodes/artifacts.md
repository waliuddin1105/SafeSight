---
id: artifacts
type: component
status: implemented
links: [adr-0006, architecture, verification]
---
# Artifacts

## What and why

Versioned hashed model cards separate PASS activation from explicit evaluation-only selection. Runtime never downloads assets or imports trainers; supported swaps use configuration and files.

## Inputs and outputs

See the typed contracts and API routes for the concrete boundary. Configuration comes from YAML/environment; errors remain visible to reviewers or operators.

## Gotchas

Synthetic checks establish software execution only. Follow docs/VERIFY.md for current verification limits.

Model sharing uses tools/share_model.py export/fetch with bundle and per-file hashes. Imported versions remain inactive; see docs/MODEL_SHARING.md.
