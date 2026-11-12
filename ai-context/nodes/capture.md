---
id: capture
type: pipeline
status: implemented
links: [architecture, verification]
---
# Capture

## What and why

Browser JPEG packets use monotonic sequence/time values, bounded PostgreSQL/filesystem spooling and explicit drop counts. RTSP hosts require allowlisting; native USB is supported. No audio.

## Inputs and outputs

See the typed contracts and API routes for the concrete boundary. Configuration comes from YAML/environment; errors remain visible to reviewers or operators.

## Gotchas

Synthetic checks establish software execution only. Follow docs/VERIFY.md for current verification limits.
