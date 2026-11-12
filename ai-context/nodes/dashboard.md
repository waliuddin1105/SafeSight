---
id: dashboard
type: component
status: implemented
links:
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
