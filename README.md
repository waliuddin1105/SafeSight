# SafeSight

Industrial safety monitoring with five independently trained models, a Flask API,
PostgreSQL, and a React reviewer dashboard. Browser cameras and recorded video are
supported. PPE detection is outside scope. See [the implementation plan](docs/PLAN.md),
[verification record](docs/VERIFY.md), and [AI context map](ai-context/INDEX.md).

## Windows setup

Supported Python: **3.11**. Node 22.12+ or 24 and PostgreSQL 16 are required for local operation.
GPU configuration is optional. The default installation uses CPU wheels.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check
python tools/verify_environment.py
Copy-Item .env.example .env
```

Set SECRET_KEY to a random value of at least 32 characters; set DATABASE_URL to your
Supabase PostgreSQL connection (psycopg prefix and sslmode=require). Also set
SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY. See [Supabase setup](docs/SUPABASE.md). Generate session-signing secrets with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

The application fails clearly if its session secret is missing. Do not commit .env.
Compose inherits the same hosted DATABASE_URL; no local PostgreSQL password is needed.

For NVIDIA acceleration, install the matching CUDA variants **after** the root requirements:

```powershell
python -m pip install --force-reinstall torch==2.7.1+cu126 torchvision==0.22.1+cu126 --index-url https://download.pytorch.org/whl/cu126
python -m pip check
python tools/verify_environment.py
```

Use an NVIDIA driver compatible with that PyTorch CUDA build. No separate CUDA toolkit
is needed for these wheels. Newer GPU architectures may need a newer supported PyTorch
pair; record dependency changes in an ADR and recheck both requirement sets. The code
probes a real CUDA operation and falls back to CPU if CUDA is absent/incompatible.
CPU operation can be slow; no training speed or real-time throughput is guaranteed.

Training alone can use a separate environment with training/requirements.txt; run
tools/verify_environment.py --training-only there. The two requirement closures use
identical shared versions. MediaPipe 0.10.31's Windows wheel has an incorrect internal
platform tag: uv pip check flags it, while standard pip check and actual Windows
PoseLandmarker execution pass. Use the Tasks API, not the removed solutions API.

## Collect and train

On the training computer, public-source acquisition can be started with
`python tools/prepare_datasets.py` (all four tasks except guard), or previewed without
downloads with `python tools/prepare_datasets.py all --plan`. See
[dataset preparation](docs/DATASET_PREPARATION.md) for credentials, paths, local archives
and readiness statuses. Current public sources still need annotation/provenance work;
download completion does not imply that the strict training dataset contract is met.

Read datasets/SLUG/README.md before collecting data. Supply images/clips, annotations,
manifest provenance exactly as documented. Four use cases train on images; guard
requires ordered clips. Event videos are needed only for separate alert qualification.
Splits are generated automatically by original video/scene/session; never randomly split frames.
The repository contains no real datasets. Training never writes to supplied datasets.

```powershell
python tools/validate_dataset.py phone_usage
python training/phone_usage/train.py --config training/phone_usage/config.yaml
python tools/validate_dataset.py all
```

Replace phone_usage with body_state, cigarette_smoking, entrance_guard or fire_smoke.
Each entrypoint runs independently. Registered pretrained assets are checksum-verified
on first training use, or can be fetched explicitly:

```powershell
python tools/fetch_pretrained.py yolo11s.pt pose_landmarker_lite.task
```

Recipes, device selection, batch sizes and quality targets live beside each trainer in training/<slug>/config.yaml.
Resume with --resume PATH_TO_LAST_CHECKPOINT. Resume rejects changed datasets/configs;
completed reports are reused rather than silently evaluating test again. YOLO checkpoints
are under the run's fit/weights directory; classifier checkpoints are run/last.pt.

Runs write artifacts/runs/SLUG/RUN_ID and models/SLUG/versions/RUN_ID, including reports
and model cards. Training exit 0 means fitting/validation completed, not a production
quality PASS. Structural/execution failures exit 1. Training never auto-activates a model.
Qualify a frozen version after supplying annotated validation/test recordings:

```powershell
python tools/validate_dataset.py phone_usage --qualification
python tools/qualify_model.py phone_usage RUN_ID
```

Qualification exits 0 for PASS, 2 for completed quality FAIL and 1 for execution/data
errors. Only passing real-data qualification can activate a model. Synthetic artifacts
remain evaluation-only. See [improvements and verification](docs/IMPROVEMENTS.md).

Only passing real-data versions activate automatically. Select an existing candidate with:

```powershell
python tools/activate_model.py phone_usage RUN_ID
```

Use --evaluation and EVALUATION_MODE=true to inspect an unqualified candidate. Restart
the worker after a model change. Weights, class order, preprocessing version and SHA-256
must agree with the card. New frameworks require an adapter; supported model swaps do not.

## Run the application

```powershell
python -m alembic upgrade head
python -m flask --app safesight.backend.app:create_app grant-user AUTH_USER_UUID person@example.com --role admin
Set-Location frontend
npm ci
npm run build
Set-Location ..
python -m safesight.backend
```

In a second activated terminal at the project root:

```powershell
python -m safesight.worker
```

First create/invite an Auth account in Supabase and grant its UUID application access.
Open http://127.0.0.1:5000. Sign in using that email/password, create a location and browser/upload source under
Workspace setup, then start capture or queue a recording. Browser camera access requires
localhost or HTTPS and explicit permission. Audio is disabled. No models are ready until
valid artifacts are present; the dashboard displays unavailable/evaluation states.

Uploaded recordings without capture timestamps retain media offsets and show unknown
capture time. API uploads can include an ISO-8601 captured_at with timezone. Filters use
capture time when known and ingestion time otherwise. Evidence is authenticated and
review decisions remain in history. Source setup and frame control use /api/v1; auth/me
returns the CSRF token required by every mutation in X-CSRF-Token.

For RTSP, an administrator supplies config.uri using POST /api/v1/sources and explicitly
allows its hostname in configs/application.yaml. USB sources use config.device (default 0)
and run natively on the backend machine. Container USB passthrough is host-specific; use
browser capture or RTSP with Compose. One live source is supported initially.

## Docker

```powershell
docker compose up --build -d
docker compose run --rm api python -m flask --app safesight.backend.app:create_app grant-user AUTH_USER_UUID person@example.com --role admin
```

Compose starts migrations, API and worker against Supabase PostgreSQL. Models are mounted read-only; media
uses a named volume. It exposes the dashboard on localhost:5000. The image is
CPU-first; GPU passthrough additionally requires a compatible NVIDIA container runtime and
CUDA wheels in the image. Docker runtime has not been verified on this host.

## Software checks

```powershell
python -m pip install -r requirements-dev.txt
python tools/generate_fixtures.py all
python tools/validate_dataset.py all --root tests/fixtures/datasets --allow-synthetic
python training/body_state/train.py --smoke
python training/phone_usage/train.py --smoke
python training/cigarette_smoking/train.py --smoke
python training/entrance_guard/train.py --smoke
python training/fire_smoke/train.py --smoke
python -m pytest -q
python tools/build_context_graph.py --check
```

Synthetic data and models stay in tests/fixtures. Fixtures prove execution, not behavior
accuracy. Integration tests default to disposable SQLite; to exercise PostgreSQL set
SAFESIGHT_TEST_DATABASE_URL to a disposable database whose name is safesight_test. Tests
reset that database. Frontend browser checks use npm test against a test server at :5000,
with the integration test's admin account. Never run those against a production server.

### M0-M7 checks without training

The completion pass did not execute any training entrypoint. Use these commands to
check the modules with explicitly untrained inference artifacts:

```powershell
python tools/generate_fixtures.py all
python tools/generate_inference_fixtures.py
python -m pytest -q
python tools/check_release.py
```

The inference fixture generator initializes random detector weights and fixed classifier
logits, marks every card synthetic/FAIL, and never runs an optimizer or trainer. The
training smoke commands above are optional future checks, separate from this workflow.

### Qualify the smoking/fire combination

Independent model training remains independent. To qualify the combined smoke-source
decision, supply joint events/fusion_val.jsonl and events/fusion_test.jsonl under the
fire_smoke dataset, with the same event-video record format and disjoint source/session
groups. Each record's events must label all relevant smoking, fire, hazardous_smoke and
uncertain_smoke intervals; retain negative recordings with an empty events list.
Both source datasets' provenance manifests are checked against training leakage.

```powershell
python tools/evaluate_fusion.py --config configs/fusion.yaml
```

This performs inference/evaluation only. It calibrates on validation and measures test
after freezing thresholds. A passing fusion_card.json binds policy/thresholds to the
exact installed model cards. A model swap invalidates the old joint qualification;
re-evaluate and restart the worker. Without a matching PASS, unresolved smoke remains
reviewable and strong flame detections remain enabled.

Worker snapshots now persist source-local temporal history, pending evidence and
classifier-window metadata in PostgreSQL, with checksum-addressed media blocks under
MEDIA_ROOT/recovery. Blocks are reused and obsolete windows are collected. Recovery accepts only matching model
and policy fingerprints. Changed/incompatible state is reported visibly. Apply all
migrations before starting the updated worker. See docs/MILESTONES.md for status.

## License and limitations

AGPL-3.0 has no license fee. This project includes Ultralytics code/models under AGPL;
comply with applicable source-sharing requirements when distributing or providing network
access. Proprietary use can require an enterprise license. Review third-party model and
dataset rights independently. LICENSE contains the full AGPL text.

Occluded activity with no visible cue is indeterminate. A visible inspection does not prove
inspection thoroughness. Posture policies need location/task exceptions. Synthetic checks
cannot establish real quality, prevent retraining, or prove performance on unavailable hardware.

Dataset partitioning is automatic: see [unsplit input workflow](docs/AUTOMATIC_SPLITS.md).

Share trained weights using the [model bundle workflow](docs/MODEL_SHARING.md). Model binaries and datasets stay outside Git.

Deployment diagnostics, default-admin access, cleanup and backup procedures: [operations](docs/OPERATIONS.md). The generated [OpenAPI contract](docs/openapi.json) documents the REST surface.
