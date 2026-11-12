---
id: evidence
type: component
status: implemented
links:
- architecture
- verification
---
# Evidence

## What, why and how

Evidence consists of an authenticated JPEG and an H.264 clip, with explicit pending/ready/failed state and checksum. Pending windows are recovered from database snapshots.

## Inputs and outputs

Input: source-local timestamped JPEG ring. Output: media files and Evidence rows linked to incidents.

## Gotchas

Encoding preserves relative presentation timestamps, including gaps. Stopped sessions finalize available footage. Disk/codec failures remain visible and are not assigned fabricated evidence.

Recovery media is stored as immutable checksum-addressed files under MEDIA_ROOT/recovery. Database snapshots hold references; periodic collection removes obsolete blocks. No full media window is rewritten into PostgreSQL each frame.
