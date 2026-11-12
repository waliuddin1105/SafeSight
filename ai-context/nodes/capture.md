---
id: capture
type: pipeline
status: implemented
links: [adr-0010, adr-0007, architecture, verification]
---
# Capture

## What and why

Browser JPEG packets use monotonic sequence/time values, bounded PostgreSQL/filesystem spooling and explicit drop counts. RTSP hosts require allowlisting; native USB is supported. No audio.

## Inputs and outputs

See the typed contracts and API routes for the concrete boundary. Configuration comes from YAML/environment; errors remain visible to reviewers or operators.

## Gotchas

Synthetic checks establish software execution only. Follow docs/VERIFY.md for current verification limits.

Protected image/video evidence and frame uploads retain cookie/CSRF access under Supabase-mediated sessions.

Uploads pin versions, source/location settings and sampling. Jobs have protected video seeking, cancellation, history, predictions and optional event-ground-truth metrics. Camera reads are bounded outside the worker process.
