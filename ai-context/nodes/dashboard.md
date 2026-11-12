---
id: dashboard
type: component
status: implemented
links:
- video_testing
- adr-0007
- architecture
- quality
---
# Dashboard

## What, why and how

React provides operational health, camera capture, uploads, filtered incidents, evidence and human review.

## Inputs and outputs

Input: REST polling and getUserMedia. Output: bounded JPEG requests, upload jobs and append-only review actions.

## Gotchas

A reconnect starts a new capture generation and invalidates old callbacks. Camera permission errors and offline workers are visible. Synthetic models remain labeled evaluation only.

Incident rows and details show location. Camera loops stop on terminal session/source errors; old capture callbacks cannot cross reconnect generations. Browser review/history checks use explicit fixtures.

Login uses invited Supabase email/password through Flask. Browser tokens/localStorage are unnecessary; 401 returns to login and stops local capture.

Typed API/auth/capture/incidents/setup/testing modules replace the monolithic component. Polling rejects stale responses; dates use configured timezone, and review dialogs trap/restore focus.

Dashboard modules are formatted and distinguish collection responses from paginated lists. Optional supplied-ground-truth metrics are displayed separately from detection scores.
