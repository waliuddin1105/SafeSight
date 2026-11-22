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

Input: authenticated JSON, bounded JPEG requests with sequence/clock headers, or multipart
video/still-image uploads. Output: structured JSON errors/results and conditional media delivery.

## Gotchas

Camera clocks are normalized to each source generation. Restart clears old spool packets. RTSP hosts are allowlisted. Capture timestamps without timezone are rejected.

The app factory registers resource blueprints in backend/routes. Security, request validation, serialization, handlers and CLI are separate modules. Resources come from current_app extensions; route URLs and response behavior are preserved.

Login now accepts email/password through Supabase; protected media and API calls retain same-origin cookies/CSRF. Logout destroys backend tokens even during provider outages.

Jobs history/cancel/video/predictions/incidents/metrics and model-version listing are implemented. OpenAPI is generated and served at the authenticated /api/v1/openapi.json endpoint.

Uploads accept MP4/MOV/MKV/AVI and JPEG/PNG/WebP. Images are pixel-bounded, decoded once and
converted to a one-frame worker job. Live source start optionally accepts unique model slugs,
allowing the testing page to choose active models without changing inference versions.
Multipart source_id is optional: omission atomically reuses a neutral internal Testing Lab
location/source, while explicit upload sources retain location policy testing.

OpenAPI now documents optional event ground truth and public job schemas; private session/credential tables remain excluded.

The frontend API client handles empty/non-JSON proxy errors and HTTP no-content responses explicitly. Initial backend connection failures are shown on sign-in; login refreshes the CSRF token before retrying after server restart.

Vite development proxy explicitly preserves the browser-facing Host (changeOrigin=false), allowing Flask to enforce matching Origin/Host without weakening CSRF protection.

Readiness requires a live worker and at least one available model; per-model status
still reports unavailable models. Overview polling pauses while the Testing page is
open, reducing repeated authenticated database requests.

`GET /api/v1/overview` returns sources, locations, worker/model health and the canonical
filtered incident page from one database session. `GET /api/v1/jobs/{id}/results`
returns job state, incremental prediction frames, incidents and optional user-truth
metrics. Existing granular routes remain compatible. The overview polls every five
seconds while visible; active testing results poll every two seconds, drain paginated
frames, and stop at a terminal state. Job history refreshes every ten seconds.
