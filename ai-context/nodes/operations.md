---
id: operations
type: component
status: implemented
links: [deployment, authentication, schema, verification]
---
# Operational diagnostics and explicit account bootstrap

## What, why and how
tools/doctor.py checks hosted DB/TLS, migrations, RLS, Auth availability, profile
bindings and model artifact/context hashes without printing credentials. tools/cleanup.py
is dry-run by default and can prune expired sessions/counters and old orphan uploads.
No incident evidence is automatically deleted.

## Inputs and outputs
Environment database/Auth configuration; optional SUPABASE_SECRET_KEY is read only by
tools/bootstrap_admin.py for an explicit confirmed Supabase account. It creates a
generated password in ignored artifacts/private/admin-credentials.json, grants admin
and verifies identity; reruns preserve credentials and never silently reset passwords.
Runtime sign-in still uses the publishable key and standard Supabase Auth.

## Gotchas
Credentials/private backups must stay out of Git and Docker build contexts. Account
bootstrap is optional operator tooling, never an automatic startup action or login bypass.
Real bootstrap, login, forced refresh, role checking and logout were verified separately
from fake-boundary test accounts. Backup/restore procedures are in docs/OPERATIONS.md.
