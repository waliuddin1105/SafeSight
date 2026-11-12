---
id: review
type: feature
status: implemented
links: [architecture, verification]
---
# Review

## What and why

Paginated type/date/location/status filters, authenticated evidence and append-only confirmed/dismissed reviews. Model uncertainty remains separate from review status.

## Inputs and outputs

See the typed contracts and API routes for the concrete boundary. Configuration comes from YAML/environment; errors remain visible to reviewers or operators.

## Gotchas

Synthetic checks establish software execution only. Follow docs/VERIFY.md for current verification limits.
