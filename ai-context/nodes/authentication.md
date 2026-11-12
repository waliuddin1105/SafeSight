---
id: authentication
type: api
status: implemented
links: [architecture, verification]
---
# Authentication

## What and why

Cookie sessions, CSRF-protected mutations, local reviewer/admin roles and bounded login attempts. Bootstrap users through Flask CLI. No built-in password or demo account.

## Inputs and outputs

See the typed contracts and API routes for the concrete boundary. Configuration comes from YAML/environment; errors remain visible to reviewers or operators.

## Gotchas

Synthetic checks establish software execution only. Follow docs/VERIFY.md for current verification limits.
