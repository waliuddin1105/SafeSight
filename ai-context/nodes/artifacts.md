---
id: artifacts
type: component
status: implemented
links: [adr-0006, adr-0012, architecture, verification]
---
# Artifacts

## What and why

Versioned hashed model cards separate PASS activation from explicit evaluation-only selection. Runtime never downloads assets or imports trainers; supported swaps use configuration and files.

## Inputs and outputs

See the typed contracts and API routes for the concrete boundary. Configuration comes from YAML/environment; errors remain visible to reviewers or operators.

## Gotchas

Synthetic checks establish software execution only. Follow docs/VERIFY.md for current verification limits.

Immutable versioned cards use normal Git and versioned weights use Git LFS so clones share
the same relative artifact layout. `tools/share_model.py export/fetch` remains the verified
offline/shared-drive fallback. Imported versions remain inactive; see docs/MODEL_SHARING.md.

Missing active cards never expose absolute device paths. Health reports distinguish no
installed model from installed evaluation versions; only an explicit passing activation
creates the production root card.

Shared bundles optionally include training recipes/validation reports to support qualification on another machine. Qualification reads frozen temporal policy and local preprocessing assets; no user dataset or secret is bundled.
