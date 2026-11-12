---
id: architecture
type: architecture
status: implemented
links:
- datasets
- training
- inference
- api
- schema
- dashboard
- dependencies
- deployment
- verification
- body_state
- phone_usage
- cigarette_smoking
- entrance_guard
- fire_smoke
- adr-0001
- authentication
- evidence
- capture
- worker
- review
- artifacts
- adr-0002
- recovery
- fusion_calibration
- detection_metrics
- preprocessing
- release_checks
- adr-0003
---
# Architecture

Independent models and typed adapters; Flask and a separate worker use PostgreSQL and bounded filesystem spooling. Inputs are video frames; outputs are reviewable incidents. Missing capabilities are explicit.
