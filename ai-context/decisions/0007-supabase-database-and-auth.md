---
id: adr-0007
type: decision
status: accepted
links: [authentication, api, schema, deployment, verification]
---
# Supabase PostgreSQL and Auth replace local credentials

## Context
The user requested Supabase DB/Auth across the codebase and removal of replaced code.

## Options considered
Frontend bearer tokens with a new SDK; backend-mediated Supabase Auth retaining
same-origin cookies for media; continuing local passwords.

## Decision
Supabase Auth owns credentials. Flask exchanges and validates tokens through Auth's
HTTPS API. Opaque browser sessions refer to backend-only token records; CSRF and
session signing remain. SafeSight roles are provisioned by grant-user using Auth UUIDs.
No self-enrollment, client metadata roles, local password hashes or create-user remain.
Supabase identity validation runs at most every 30 seconds per session, with serialized
refresh and immediate local profile checks. PostgreSQL is supplied through environment
URLs, including an optional separate migration URL. Remove bundled Compose PostgreSQL.
Enable restrictive RLS on application tables so publishable keys cannot bypass Flask.

## Consequences
Existing profile/review IDs remain; old credentials cannot be recovered. New accounts
must be created/invited in Supabase and explicitly granted application access. Flask
SECRET_KEY stays necessary. No frontend token storage or Supabase admin key is needed.
Evidence remains local. Real user login cannot be claimed from boundary fakes alone.
