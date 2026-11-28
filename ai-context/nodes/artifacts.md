---
id: artifacts
type: component
status: implemented
links: [adr-0006, adr-0012, adr-0013, architecture, verification]
---
# Artifacts

## What and why

Schema-v2 model cards preserve immutable training/runtime facts. Separate content-addressed
qualification attestations hold calibrated thresholds, metrics and PASS/FAIL status; a small
deployment pointer binds the exact card and PASS attestation selected for production. Runtime
never downloads assets or imports trainers.

## Inputs and outputs

See the typed contracts and API routes for the concrete boundary. Configuration comes from YAML/environment; errors remain visible to reviewers or operators.

## Gotchas

Synthetic checks establish software execution only. Follow docs/VERIFY.md for current verification limits.

YOLO model cards may preserve a checkpoint's class order when it is a permutation of the
use-case taxonomy; inference maps class IDs through that card order. Unknown, missing, or
duplicate class names remain incompatible.

Immutable versioned cards use normal Git and versioned weights use Git LFS so clones share
the same relative artifact layout. `tools/share_model.py export/fetch` remains the verified
offline/shared-drive fallback. Imported versions remain inactive; see docs/MODEL_SHARING.md.

Missing deployments never expose absolute device paths. Health reports distinguish no
installed model from installed evaluation versions; production loading requires a matching
PASS attestation. Schema-v1 cards remain read-only compatibility inputs during migration.

Shared bundles optionally include training recipes, reports, and matching qualification
attestations. Qualification reads frozen temporal policy and local preprocessing assets; no
user dataset or secret is bundled.
