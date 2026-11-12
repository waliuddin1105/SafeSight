---
id: verification
type: component
status: implemented
links:
- adr-0007
- architecture
- quality
---
# Verification

## What, why and how

Current checks cover M0-M7 without executing a train.py file or optimizer. Runtime artifacts are generated as explicitly untrained fixtures.

## Inputs and outputs

Input: unit/integration/browser acceptance tests and tools/check_release.py. Output: recorded pass/failure evidence in docs/VERIFY.md and milestone status in docs/MILESTONES.md.

## Gotchas

Do not confuse historical synthetic training reports with verification of the updated trainers. No real data accuracy or GPU/Docker claim is established here.

Current result: 26 Python checks, TypeScript build, browser acceptance and source/release contracts pass. No train.py entrypoint was executed in the completion pass. Docker runtime remains unverified locally.

Supabase identity/session tests use an explicit fake HTTP boundary against disposable PostgreSQL, not a production auth bypass. Remote connectivity and schema migration are checked separately; no real user password login is claimed.

P1-P8 verification uses non-training state/fixture tests and PostgreSQL/browser integration. Real default-admin Supabase login/refresh/logout and browser login/logout pass. Benchmark and Docker limitations are explicit in docs/VERIFY.md.
