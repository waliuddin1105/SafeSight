---
id: authentication
type: api
status: implemented
links: [adr-0007, architecture, verification]
---
# Authentication

Supabase Auth owns credentials and session validation; Flask keeps opaque HttpOnly cookies and CSRF. Backend-only auth_sessions stores tokens, with serialized refresh and 30-second identity revalidation. grant-user binds an Auth UUID to a local role; no client-metadata roles, password_hash or create-user remain. See docs/SUPABASE.md.
