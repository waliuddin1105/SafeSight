---
id: recovery
type: pipeline
status: implemented
links: [adr-0010, worker, architecture]
---
# Recovery

## What, why and how

Database RuntimeSnapshot records commit source context and pending evidence together with incident writes. The typed codec whitelists inference classes, primitive containers and uint8 media; it never executes serialized code. Matching model/policy fingerprints restore context; mismatches visibly fail unavailable evidence.

## Inputs and outputs

Follow the linked component for the concrete data contract and source entrypoints.

## Gotchas

Untrained fixtures exercise software contracts; field performance requires measured held-out data.

Recovery media is stored as immutable checksum-addressed files under MEDIA_ROOT/recovery. Database snapshots hold references; periodic collection removes obsolete blocks. No full media window is rewritten into PostgreSQL each frame.

Job snapshots recover using their own pinned fingerprint, independently of subsequently activated global cards. Per-frame records are unique by job/time and cursors are monotonic.
