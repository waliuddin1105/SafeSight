---
id: worker
type: component
status: implemented
links:
- adr-0010
- architecture
- verification
---
# Worker

## What, why and how

One PostgreSQL advisory-lock owner processes live frames before queued uploads. Source generation isolates temporal state, trackers, classifier windows and frame history.

## Inputs and outputs

Input: bounded FramePacket spool, leased jobs, source/location policy and model cards. Output: incidents, evidence, heartbeat, cursor and atomic RuntimeSnapshot.

## Gotchas

Snapshots use a typed JSON codec with compressed media, not executable pickle. Resume preserves committed windows and avoids duplicate-frame side effects. Model/policy changes invalidate incompatible snapshots visibly.

Recovery media is stored as immutable checksum-addressed files under MEDIA_ROOT/recovery. Database snapshots hold references; periodic collection removes obsolete blocks. No full media window is rewritten into PostgreSQL each frame.

Pinned jobs process decoding/inference outside database transactions. Dedicated ownership is checked by backend PID before writes. Native capture uses a terminable subprocess. See ADR 0010.

Per-frame pose extraction is conditional on a selected, available pose-dependent model
(`body_state`, `phone_usage`, `cigarette_smoking`, or `entrance_guard`). Fire/smoke-only
jobs skip MediaPipe; fire detection, smoke spread, smoothing, and uncertainty remain active.
Qualified smoking/fire fusion still receives pose because selecting smoking requires it.

The worker reuses a single pose extraction for body classification and person context.
Recovery state is committed once with each processed frame; clip completion does not
repeat that checkpoint. Heartbeats are limited to five-second intervals. An active
browser source without a pending frame yields the worker to queued upload jobs.
Clip decoding and MP4 encoding occur outside database transactions; the evidence
state is committed afterward, including encoding failures.
Uploaded recordings decode at most eight sampled frames per chunk. Detector batches
are evaluated before a single transaction commits the ordered frame results, job
cursor, incident changes and recovery snapshot. A failed commit restores the last
committed snapshot. A single evidence thread encodes clips; pending evidence retains
its snapshot until completion and remains recoverable after restart.

Session cleanup runs at most every five seconds and resolves all tracked sources and
jobs with set-based queries. Terminal job/source transitions request immediate cleanup,
while pending evidence continues to retain recovery state. Recovery-blob collection
and expired auth cleanup run at five-minute intervals only when no upload work is
available. Ownership is checked immediately before each mutation rather than on every
idle loop iteration.
