---
id: adr-0015
type: decision
status: accepted
links: [training, fire_smoke, dataset_fire_smoke, adr-0014]
---
# ADR 0015: specialize training for the curated fire/smoke corpus

## Context

The approved generic detector recipe allowed 100 epochs with patience 20. The curated
fire/smoke corpus contains 268,142 accepted still images, so each epoch already presents a
large and diverse training set. The finalized corpus lives at `datasets/fire_smoke_curated`
and its first published manifest omitted still-image timing fields.

## Options considered

- Keep the generic 100-epoch recipe and manually select the curated config on every run.
- Rewrite the finalized dataset manifest in place.
- Specialize the fire/smoke recipe and normalize absent still-image timing only in staging.

## Decision

Point both fire/smoke recipes at the read-only curated corpus. Cap training at 50 epochs
with early-stopping patience 8. Preserve all corpus files; generated split manifests supply
`start=end=0.0` when a flat still-image record omits timing. Future curated builds emit these
fields directly.

## Consequences

Default fire/smoke training uses the intended corpus and stops sooner after validation stalls.
Changing this recipe invalidates resume compatibility with earlier fire/smoke runs. Image
training still does not qualify temporal alert performance; annotated real videos remain
required for deployment PASS.
