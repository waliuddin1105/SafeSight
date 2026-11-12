---
id: api
type: api
status: implemented
links:
- adr-0005
- architecture
- quality
---
# Api

## What, why and how

Flask /api/v1 exposes local auth/CSRF, source/location creation, start/stop/frame control, uploads/jobs, incident list/detail/review, evidence and health.

## Inputs and outputs

Input: authenticated JSON, bounded JPEG requests with sequence/clock headers, or multipart video. Output: structured JSON errors/results and conditional media delivery.

## Gotchas

Camera clocks are normalized to each source generation. Restart clears old spool packets. RTSP hosts are allowlisted. Capture timestamps without timezone are rejected.

The app factory registers resource blueprints in backend/routes. Security, request validation, serialization, handlers and CLI are separate modules. Resources come from current_app extensions; route URLs and response behavior are preserved.
