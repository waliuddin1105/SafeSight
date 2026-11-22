---
id: adr-0013
type: decision
status: accepted
links: [artifacts, training, inference, quality, adr-0012]
---
# Immutable model cards, qualification attestations, and deployments

## Context

Schema-v1 qualification rewrote a version's model card with thresholds, test metrics, and
PASS/FAIL state. That made the card hash mutable after training and could leave pinned jobs,
database model rows, shared bundles, and fusion records referring to different content.

## Options considered

Continue mutating cards with stronger synchronization; create a new run ID after every
qualification; or keep training facts immutable and bind separate qualification/deployment
documents by canonical hashes.

## Decision

Schema-v2 model cards contain immutable training and runtime-interface facts. Qualification
writes a content-addressed attestation containing calibrated thresholds, measured results,
support, and quality status without changing the card. Production activation writes a small
deployment pointer bound to exact card and attestation hashes. New qualification data creates
a new attestation. Schema-v1 cards and pinned snapshots remain readable during migration but
new training emits v2 only.

Detector cards also separate an inference candidate floor from the dashboard display floor.
The inference floor defaults to 0.05 and the display floor to 0.10; alert thresholds remain
qualification outputs.

## Consequences

Production loading requires a matching PASS attestation. Explicit testing may load an
unqualified version in evaluation mode. Bundles carry matching attestations, fusion binds
canonical card hashes, and changing card or qualification content invalidates deployment.
The testing dashboard may reveal retained low-confidence candidates without changing alerts.
