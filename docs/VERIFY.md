# M0-M7 verification record
## Approved P1-P8 improvement verification

2026-11-12: 72 Python tests pass (55 unit, 17 PostgreSQL integration). Four browser
workflows pass: sign-in/filter/permission denial, capture reconnect, incident review,
and a real fixture recording through the worker with selected-model playback/history.
The original three and added recording workflow were verified across browser runs.
TypeScript/Vite production build, Ruff, OpenAPI stale-contract check, release contracts
and context graph pass. No train.py, optimizer step or model fitting was executed.

Added checks cover image-only training readiness, duplicate-stem staging, disk-backed
features, exact accumulation weighting, checkpoint/RNG restoration with inert state
objects, failure galleries, pinned-card replacement, queued/running cancellation,
shared atomic rate limits, concurrent refresh, disk-shortfall HTTP 507, lost ownership,
annotation-backed event matching and bounded native input using a generated video.

Local migration 0003 -> 0004 -> 0003 -> 0004 passes. Hosted Supabase is at 0004 and
all application tables exist. The requested confirmed default admin was created with
a generated password stored only in ignored artifacts/private/admin-credentials.json.
Real Supabase login, forced refresh, admin permission, protected reads and logout pass;
real browser login/logout also pass. No password, token or admin key was printed.

Synthetic inference benchmark: Windows, AMD64 Family 23 Model 113 Stepping 0,
12 logical CPUs, ~8.5 GB RAM, Python 3.11.14 and PyTorch 2.7.1+cpu. Ten blank 640x480
frames with smaller untrained fixtures measured ~9.36 FPS average and ~0.280 seconds
p95 per-frame latency. This excludes real camera conditions, cloud-DB pipeline cost
and full entrance observation-window behavior. It is not model accuracy, target-GPU
performance or production throughput evidence. Full JSON is artifacts/reports/benchmark.json.

Docker is unavailable locally. CI now includes image build, Compose startup/restart
and media-volume persistence, but remote CI has not been executed in this session.
Real training, real-data accuracy/qualification, hardware cameras, GPU throughput and
backup restoration remain unverified. Existing instruction against running trainers
remains in force. Synthetic model cards remain FAIL/evaluation-only.


## Supabase database and authentication verification

2026-11-12: 49 unit tests and nine PostgreSQL integration tests pass (58 total).
Three browser acceptance tests pass using an explicit fake Supabase HTTP boundary.
TypeScript/Vite production build, Ruff, context graph and release contracts pass.
Local PostgreSQL migration 0002 -> 0003 -> 0002 -> 0003 passes; old password hashes
cannot be restored by downgrade. No authentication test calls a real password grant.
Tests cover refresh, serialized session handling, provider rejection/outage, preserving
rotated tokens after identity-check outage, logout, disabled/unprovisioned profiles,
reviewer permissions, CSRF, and existing camera/upload/incident/evidence flows.

Hosted Supabase migrations were applied through 0003. Read-only checks confirm TLS
to the pooler, absence of password_hash, session-table RLS, anonymous rejection and
live application health. No SafeSight profiles are provisioned; a real invited user
login/refresh/logout remains unverified. Public signup settings were not changed.
SECRET_KEY remains required for opaque signed cookies. No tokens or secrets were
printed. No training ran; Docker runtime and physical cameras remain unverified.


## Config and model-sharing cleanup verification

2026-11-12: all 49 unit tests pass, including two model-transfer integrity tests
using inert synthetic bytes. Transfer tests verify round-trip, checksum rejection,
conflicting-version preservation and no implicit activation. Colocated training
configs pass release contracts, all code passes Ruff, and the context graph passes.
No training was run. Existing runtime packages and CI were retained. Root generated
Ultralytics settings and empty legacy split directories were removed; no user media
or weights were removed. Real trained-model transfer, shared-drive access and HTTPS
download have not been verified. PostgreSQL/browser integration was not rerun for
this tooling/configuration change.

## Runtime splits and backend refactor verification

2026-11-12: all 49 unit/integration tests pass against PostgreSQL 16. Includes
five runtime-split tests: deterministic group assignments, original preservation,
tamper rejection, legacy compatibility, and actual validator round-trip with synthetic
images/labels/event videos. API tests cover authentication, capture, incidents, evidence,
reviews and upload-worker processing after blueprint extraction. The SQLite fallback
worker test encountered database locking; the supported PostgreSQL run passes.
Ruff, context graph and release contracts pass. No training entrypoint was run.
Real-data split distributions and model quality remain unverified.


## Portable dataset preparation verification

Added 2026-11-12: 18 acquisition/preparation tests pass, and all 42 unit tests pass.
Checks use tiny synthetic ZIP/TAR archives and a local HTTP server: resumable/cached
downloads, checksums, disk-space rejection, safe extraction, interrupted extraction,
preservation of existing data, explicit annotation gaps, and native-bundle installation.
Native-install boundary tests explicitly mock dataset validation; the validator's own
behavior is covered separately by the existing dataset unit tests.
Ruff, release contracts and the context graph check pass. The CLI source preview passes.
No public dataset download, provider-authentication flow or training was executed.
Cross-platform support is implemented with portable Python paths; execution was verified
on Windows only. These checks establish software behavior, not model accuracy.

Completion pass: 2026-11-12. Windows 11, Python 3.11.14, CPU PyTorch 2.7.1.
No training entrypoint or optimizer was executed in this pass.

## Verified

- 26 Python tests pass, including read-only dataset checks, malformed labels/media,
  provenance leakage, minimum calibration support, object-size AP, temporal gaps and
  N-of-M behavior, joint prediction replay, crop consistency, artifact replacement,
  checksum rejection and non-executable recovery serialization.
- PostgreSQL 16 integration tests pass for authentication/CSRF, browser frame ordering,
  incident persistence, JPEG/MP4 evidence, filtering and append-only reviews.
- Worker restart tests recover pending evidence and resume a partly processed uploaded
  recording with its cursor and source-local context.
- Independent root and training-only environments pass standard pip dependency checks.
  Their initial fresh installations and import/CPU operations were verified previously;
  the requirement files did not change in this pass.
- Fresh PostgreSQL migration upgrade/downgrade/upgrade includes migration 0002.
- React TypeScript production build and npm audit pass (zero reported vulnerabilities).
- Browser checks cover sign-in/out, filtering, permission denial, successful simulated
  camera capture/reconnect, and review/history UI. Review UI uses an explicit browser
  fixture; real review persistence is covered separately by PostgreSQL tests.
- Ruff passes. The context graph passes reachability/link checks. check_release.py
  verifies dependency pin consistency, five independent entrypoints and Compose structure.

## Explicit limits

- Updated training execution, interrupted optimizer resume, and --smoke training runs
  were intentionally not executed under the user's instruction. Training code is
  covered by syntax, isolation, preprocessing and metric contract checks.
- Inference fixtures are untrained detector weights and fixed classifier logits. They
  carry synthetic/FAIL cards and do not establish real safety metrics.
- No real datasets exist in this checkout. Real accuracy, alert quality PASS, hidden
  cigarette recall and the joint fusion quality gate have not been measured.
- CUDA, physical USB/RTSP cameras and real-time target-hardware throughput are unverified.
- Docker is unavailable on this host. Image/Compose source contracts are checked; image
  build, container startup and restart/persistence need a Docker-capable host. CI includes
  an image build and non-training checks, but CI has not been run remotely in this session.
- M8 is outside this requested pass.

## Recovery behavior

The initial volatile-window limitation is superseded by ADR 0003. PostgreSQL snapshots
commit engine/sequence state and references to immutable media blocks under MEDIA_ROOT.
Blocks are checksum verified and obsolete windows are collected. Pending evidence
survives a matching worker restart. Changed model/policy context or missing/corrupt
recovery media is explicitly rejected rather than used to fabricate evidence.
