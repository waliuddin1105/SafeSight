# Approved image-based improvements

Implementation follows P1-P8 from the approved plan. Training scripts remain prohibited
from execution during implementation. Each completed stage is verified and committed.

## P1-P2: training lifecycle

Four use cases train on images; entrance_guard requires sequences. Training performs
model fitting/validation and exports an evaluation-only card. It does not touch test
metrics or require event videos. Use ordinary independent training commands later.

```text
python tools/validate_dataset.py phone_usage
python tools/validate_dataset.py phone_usage --qualification
python tools/qualify_model.py phone_usage RUN_ID
```

Qualification uses the saved training configuration, rejects changed training samples,
calibrates on validation events, evaluates held-out test data and writes a separate
qualification report/hash. Repeated qualification reuses its completed report.
Synthetic candidates never auto-activate. A production PASS is required for activation.

Frozen classifier representations are content-addressed and disk-backed. Sample staging
is collision-safe. Interrupted/memory-failed classifier epochs restore full model,
optimizer/scheduler and RNG state before retrying with smaller batches. CPU state files
avoid duplicating the model on GPU. These code paths are checked without running a trainer.

## P3: measured diagnostics

Training writes source/class/tiny-object inventory and pose failures. Qualification
records actual false-positive/negative examples and a bounded HTML gallery. Model and
deployed pipeline metrics are separately labeled. tools/compare_models.py compares
validation metrics only on matching real-data fingerprints and can write an explicit
fallback recipe. It does not run training or select using test data.

## P4-P6: recorded-video testing and maintainable dashboard

The workspace selects one/multiple model versions, explicit evaluation testing,
optional capture time, and optional event ground truth. Each job pins cards, hashes,
thresholds, preprocessing, sample rate, fusion and source/location rules. Model activation
is unaffected. Authenticated APIs expose history, cancellation, ranged original video,
paginated predictions and incident timelines. Playback overlays sampled boxes and lets
reviewers seek to alerts/unknown periods. Scores are not accuracy. Optional event metrics
are calculated only for completed jobs with compatible annotations; they do not qualify
models. Example annotation JSON:

```json
{"events":[{"slug":"fire_smoke","subtype":"fire","start":1,"end":3,"box":[0,0,1,1]}]}
```

Decoding and inference occur outside claim/progress transactions. Frame results are
unique by job/time, cursor updates are monotonic and cancellation is durable. Worker
ownership uses a dedicated autocommit connection and fails closed on connection change.
Native capture uses a bounded subprocess. Missing models/frames, decoder failure and disk
shortfalls stay visible. UI modules are typed and reject stale polling results; source
setup includes models, RTSP, zones and policies. Time inputs use configured timezones;
review dialogs support keyboard focus/Escape. OpenAPI covers registered routes and public
resource fields, with a stale-contract check.

## P7: Supabase operation

Shared atomic login limits replace in-memory counters; logout and refresh serialize.
Worker/cleanup expire sessions/counters. Doctor checks TLS, migration, RLS, roles, Auth
and model files/context. Production requires HTTPS/secure cookies. A requested default
admin was provisioned through Supabase's admin API with a generated local-only password;
no hardcoded login or auth bypass exists. See OPERATIONS.md for provisioning and backup.

## P8: acceptance and explicit limits

Unit/integration/browser tests exercise fixtures and provider boundaries; real Supabase
account login/refresh/logout is verified separately. Benchmark output identifies hardware
and limitations. CI adds Compose startup, restart and volume persistence checks. Docker
is not installed on this development host, so those container checks remain pending CI.
Real-data training/accuracy, CUDA performance and physical camera checks remain unverified.
No training script was run. Exact current results are recorded in VERIFY.md.
