# Supabase PostgreSQL and Auth

Supabase handles email/password credentials, confirmation, refresh and revocation.
SafeSight retains application profiles, reviewer/admin roles and review history.
There is no local-password login, public signup endpoint or Supabase admin-key dependency.

## Environment and database

Set the following in the ignored root .env:

```dotenv
DATABASE_URL=postgresql+psycopg://USER:ENCODED_PASSWORD@SESSION_POOLER_HOST:5432/postgres?sslmode=require
MIGRATION_DATABASE_URL=
SUPABASE_URL=https://PROJECT.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
SECRET_KEY=GENERATE_A_RANDOM_VALUE_AT_LEAST_32_CHARACTERS
SESSION_COOKIE_SECURE=false
```

Use the full Session pooler connection string from Connect when IPv4 is needed.
Keep credentials URL-encoded. Optionally use a direct connection in
MIGRATION_DATABASE_URL when reachable; otherwise migrations use DATABASE_URL.
Set SESSION_COOKIE_SECURE=true behind production HTTPS. SECRET_KEY signs SafeSight
cookies and is separate from all Supabase keys. No secret/service-role key is needed.
The API and worker require a trusted database owner/BYPASSRLS connection; a browser
publishable key cannot query SafeSight tables. Never expose DATABASE_URL in Vite.

```text
python -m alembic upgrade head
```

Migration 0003 drops password_hash permanently, preserves existing profile IDs/review
history, adds unique nullable Supabase identity bindings and backend sessions, and
enables RLS on SafeSight's application tables with no public API policies. It does
not alter Supabase auth.users or unrelated tables. Existing unbound local accounts
cannot log in; provision a new bound profile. Downgrade cannot restore passwords.
Compose now runs migration/API/worker against the hosted URL, with local evidence
volumes; it neither starts PostgreSQL nor overrides DATABASE_URL. Keep media storage
and models on the backend host. Supabase Storage is not part of this change.

## Provision users

Create/invite the person through Supabase Dashboard Authentication > Users. Disable
public signup there for invite-only operation. Email confirmation/password setup is
managed by Supabase. Copy their Auth user UUID, then grant application access:

```text
python -m flask --app safesight.backend.app:create_app grant-user AUTH_USER_UUID person@example.com --role admin
```

Use --role reviewer for reviewers. Repeat grant-user for the same UUID to change
roles; --disabled revokes SafeSight access on the next request. This trusted operator
command does not create a Supabase account, store a password or send an invitation.
Email is a display label; authorization binds to the verified Supabase UUID. Client
user_metadata never grants roles. Reusing an existing profile email fails visibly
rather than silently rebinding a historical identity.

## Browser and API behavior

Sign in using email/password. POST /api/v1/auth/login accepts {email,password};
/auth/me and /auth/logout retain their URLs. Supabase credentials are exchanged by
Flask over HTTPS, not stored locally. The browser receives an HttpOnly signed cookie
containing an opaque session ID, user ID and CSRF token; access/refresh tokens stay
in the backend-only auth_sessions table. Do not expose that table through Data API
policies or database roles. Session lifetime is eight hours.

Each protected request checks the active profile. Supabase identity is rechecked
every 30 seconds; token refresh starts within 60 seconds of expiry and uses a row
lock to serialize rotation. Provider rejection deletes the session; outages return
503 without granting access or deleting a valid session. Logout deletes local tokens
even when Supabase cannot be reached. Revocation of an external Supabase session may
take up to the 30-second validation interval to be noticed. Signed cookies and CSRF
protection remain necessary for same-origin evidence playback and browser mutations.
Old Flask cookies without an Auth session ID grant no access.

The dashboard returns to sign-in on 401 and stops local camera capture. Images,
video range requests, uploads and camera frames use the same protected cookies;
tokens never appear in evidence URLs or browser localStorage. No extra Vite secrets
or frontend Supabase SDK are necessary for this backend-mediated flow.

## Verification boundaries

Python/browser acceptance uses an explicit fake at the Supabase HTTP boundary and a
disposable PostgreSQL database. tools/browser_fixture.py refuses a database not named
safesight_test; production never installs its fake. Remote PostgreSQL/Auth connectivity
is checked separately. Real password login/refresh requires a provisioned real user;
no demo account is created and no passwords should be pasted into chat.

References: [Auth API](https://github.com/supabase/auth/blob/master/openapi.yaml),
[server-side sessions](https://supabase.com/docs/guides/auth/server-side/advanced-guide),
[database connections](https://supabase.com/docs/guides/database/connecting-to-postgres).
