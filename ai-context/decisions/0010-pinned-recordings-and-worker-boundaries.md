---
id: adr-0010
type: decision
status: accepted
links: [worker, capture, recovery, inference, schema, api, authentication]
---
# Pinned recording jobs and bounded processing

## Context
P4/P5 require reproducible video tests, cancellation and short database transactions.
P7 requires cross-process auth limits using the existing database.

## Decision
Persist model cards/hashes, selected versions, sampling, temporal policy and source/location
rules at upload. Jobs use those snapshots without activating models; identical loaded
models/context assets are reused. Keep one worker with a dedicated autocommit advisory-lock
connection and reject replaced/lost ownership connections. Claim jobs before decoding or
inference; persist unique per-frame results and monotonic cursors. Cancellation is durable.
Native camera reads use a bounded-queue subprocess so a blocked driver can be terminated.
Add paginated results/history, protected media seeking and optional annotated event metrics.
Unknown/no-result periods remain visible and scores do not imply accuracy.

## Consequences
Migration 0004 adds snapshots/results, cancelled state and shared login counters, protecting
new tables with RLS. Legacy jobs without snapshots fail with a resubmission instruction.
Public model cards remain unchanged by testing. Stored review/evidence history is preserved.
Rate limits use atomic upserts and HMAC identifiers; expired records are cleaned by worker
and explicit tooling. Real device and Docker checks remain separately reported.
