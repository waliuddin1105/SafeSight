---
id: adr-0003
type: decision
status: accepted
links: [architecture, recovery, fusion_calibration, quality, preprocessing, verification]
---
# ADR 0003: Complete runtime, fusion and verification contracts

## Context

The initial implementation had inconsistent entrance crops, unqualified cross-model suppression, insufficient validation support checks and volatile evidence windows. The user requested M0-M7 completion without running training files.

## Options

Require coupled trainers, trust independent alert metrics for fusion, or retain independent trainers and qualify the pair with a separate evaluation artifact. Retain volatile windows or persist bounded non-executable snapshots.

## Decision

Use one shared entrance crop function, card-specific temporal policies, adequately supported calibration and measured object-size AP. Train tasks independently; a separate joint validation/test command emits fusion_card.json. Only a matching PASS enables smoking-related smoke suppression. Persist engine, sequence and JPEG windows atomically in PostgreSQL with typed JSON serialization. Use isolated media copies for third-party YOLO staging and untrained fixtures for software verification.

## Consequences

This supersedes ADR 0002's volatile-window recovery limitation. Added schema migration 0002. Model/card/context changes require requalifying affected fusion and invalidate incompatible recovery state. YOLO staging needs extra disk space to protect original data. Updated training execution is intentionally unverified in this pass. Docker runtime remains unavailable locally.

Recovery storage detail: PostgreSQL commits typed state and checksummed references; immutable media blocks live under MEDIA_ROOT/recovery with periodic collection. This bounds database write volume and preserves evidence across restarts.
