---
id: authentication
type: api
status: implemented
links: [operations, adr-0010, adr-0007, architecture, verification]
---
# Authentication

Supabase Auth owns credentials and session validation; Flask keeps opaque HttpOnly cookies and CSRF. Backend-only auth_sessions stores tokens, with serialized refresh and 30-second identity revalidation. grant-user binds an Auth UUID to a local role; no client-metadata roles, password_hash or create-user remain. See docs/SUPABASE.md.

Rate limits are now cross-process PostgreSQL upserts, keyed by HMAC rather than raw IP. Logout serializes against refresh. Worker/cleanup remove expired sessions and counters.

Ordinary authenticated requests read session and user state without taking a row lock.
Only refresh, 30-second provider revalidation, expiry, and invalidation enter the
serialized path. A bounded process-local lock covers SQLite/thread concurrency while
PostgreSQL `FOR UPDATE` coordinates multiple web processes. The locked path rechecks
freshness so concurrent requests rotate a token only once.
