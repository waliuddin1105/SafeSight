---
id: deployment
type: component
status: implemented
links:
- architecture
- quality
---
# Deployment

## What, why and how

The image builds React then serves Flask under Waitress; Compose runs PostgreSQL 16, a one-shot migration service, API and worker.

## Inputs and outputs

Input: .env secrets, read-only models and persistent media/database volumes. Output: localhost dashboard and separate inference worker.

## Gotchas

Docker is unavailable on this verification host. CI includes image construction without training. Remote browser capture needs HTTPS. GPU passthrough and native USB are host-specific.
