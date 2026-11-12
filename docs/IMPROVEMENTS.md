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

## Remaining delivery milestones

P3: actionable data/model reports and fallback comparison using validation only.
P4: pinned video-testing jobs, history, cancellation and timeline results.
P5: shorter database transactions, ownership checks, bounded input/storage operations.
P6: typed modular dashboard, source settings and OpenAPI contract.
P7: shared authentication limits, diagnostics, cleanup and deployment validation.
P8: integration/browser/CI checks, measured throughput and explicit external limits.
