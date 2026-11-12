---
id: api
type: api
status: implemented
links:
- adr-0010
- adr-0007
- adr-0005
- architecture
- quality
---
# Api

## What, why and how

Flask /api/v1 exposes Supabase-mediated auth/CSRF, source/location creation, start/stop/frame control, uploads/jobs, incident list/detail/review, evidence and health.

## Inputs and outputs

Input: authenticated JSON, bounded JPEG requests with sequence/clock headers, or multipart video. Output: structured JSON errors/results and conditional media delivery.

## Gotchas

Camera clocks are normalized to each source generation. Restart clears old spool packets. RTSP hosts are allowlisted. Capture timestamps without timezone are rejected.

The app factory registers resource blueprints in backend/routes. Security, request validation, serialization, handlers and CLI are separate modules. Resources come from current_app extensions; route URLs and response behavior are preserved.

Login now accepts email/password through Supabase; protected media and API calls retain same-origin cookies/CSRF. Logout destroys backend tokens even during provider outages.

Jobs history/cancel/video/predictions/incidents/metrics and model-version listing are implemented. OpenAPI is generated and served at the authenticated /api/v1/openapi.json endpoint.

OpenAPI now documents optional event ground truth and public job schemas; private session/credential tables remain excluded.

The frontend API client handles empty/non-JSON proxy errors and HTTP no-content responses explicitly. Initial backend connection failures are shown on sign-in; login refreshes the CSRF token before retrying after server restart.
