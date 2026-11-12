# Operating SafeSight

## Checks and maintenance

```text
python tools/doctor.py
python tools/cleanup.py
python tools/cleanup.py --apply
python tools/build_openapi.py --check
python tools/compare_models.py cigarette_smoking --fallback-config
python tools/benchmark.py --fixtures --frames 10
```

Doctor is read-only; missing models remain visible. Cleanup defaults to dry-run and
preserves every referenced recording and incident evidence file. It prunes only expired
auth records and unreferenced uploads older than one day. The worker also expires auth
records regularly. Retention of incident evidence is manual and disabled by default.
Benchmark output identifies hardware and distinguishes synthetic/untrained results.
Blank-frame tests do not establish real-camera throughput or model accuracy.

## Default admin requested for development

The confirmed Supabase account admin@safesight.local has full SafeSight admin permissions.
Its generated password is saved in the ignored artifacts/private/admin-credentials.json.
There is no hardcoded/default password or automatic authentication bypass.

To provision the same account explicitly on an authorized project, put a server-only
SUPABASE_SECRET_KEY in .env and run python tools/bootstrap_admin.py. Existing credentials
are preserved and verified; an unrelated existing account is not silently reset. Remove
the optional admin key from deployment environments after provisioning when it is no
longer needed. Ordinary authentication uses only the publishable key. Never put secret
keys in VITE_* variables. Each team member should eventually have an individual account.

## Hosting and connection ownership

Keep Supabase PostgreSQL/Auth hosted and models/media on the backend machine. Use
Session pooler or direct PostgreSQL connections for the single worker's advisory lock.
Do not switch the worker to transaction pooling. API/worker connection pools are bounded.
Production requires ENVIRONMENT=production, SESSION_COOKIE_SECURE=true and an HTTPS
reverse proxy. Configure the proxy to preserve the original Origin/Host correctly;
CSRF validation must remain enabled. Default binding is localhost; do not expose the
development server directly. Camera permission requires localhost or HTTPS.

Migration 0004 adds pinned jobs, cancellation, per-frame results and shared login
limits. It is applied to the configured Supabase project. Existing jobs lacking a
snapshot must be resubmitted; model settings are never guessed retrospectively.

## Backups and restore

Back up application data, model versions/cards and the entire MEDIA_ROOT together so
evidence paths and checksums remain consistent. Keep .env secrets in a separate secure
store. Backups may contain private video and must remain outside Git/public downloads.

Use a PostgreSQL client compatible with the server. Parse DATABASE_URL into temporary
child-process PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE/PGSSLMODE values; do not pass a
SQLAlchemy +psycopg URL to pg_dump or place passwords in shell command arguments. Run:

```text
pg_dump --format=custom --schema=public --exclude-table-data=public.auth_sessions --exclude-table-data=public.login_attempts --file=APPLICATION_BACKUP.dump
```

Omit live session/refresh tokens and login counters from backups. A public-schema
backup covers application data, not Supabase-managed Auth identities. Restore to a
disposable database first using pg_restore --no-owner --no-acl, inspect migration
version and RLS, restore model/media directories, run doctor, and verify evidence
checksums and review history. Auth UUID bindings require the original Auth identities
or an explicit identity-migration procedure; never silently bind accounts by email.

Before switching production, stop the worker/API, restore the tested backup, apply
pending Alembic migrations and restart. Password hashes removed by 0003 cannot be
recovered by downgrade. Restoration of backups and Docker execution have not been
performed on this host; do not interpret these procedures as successful restore results.
