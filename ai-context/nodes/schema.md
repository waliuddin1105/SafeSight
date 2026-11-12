---
id: schema
type: schema
status: implemented
links: [adr-0010, adr-0007, "architecture", "quality"]
---
# Schema

PostgreSQL stores users, locations, sources, leased jobs, models, incidents, evidence and append-only review history. Media stays in configured storage.

Migration 0003 preserves profile IDs/reviews, removes password_hash, adds nullable unique supabase_id and backend-only auth_sessions. Restrictive RLS protects application tables from Supabase Data API access. Trusted owner/BYPASSRLS connections are required.

Migration 0004 adds job snapshots, durable cancellation, timing/counters, unique job_frames and atomic login_attempts. New tables use restrictive RLS.
