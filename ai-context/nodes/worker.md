---
id: worker
type: component
status: implemented
links:
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
