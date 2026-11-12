# SafeSight approved implementation plan

Approved for implementation by the user's “PLEASE IMPLEMENT THIS PLAN” instruction.
Project root: `SafeSight/`. Python 3.11; Windows development, Linux containers;
CPU operation is mandatory and CUDA optional. GPU type/VRAM are not required inputs.
This document records the agreed design; verification results belong in VERIFY.md.

## Scope and architecture

Five independent models: body_state, phone_usage, cigarette_smoking, entrance_guard,
fire_smoke. PPE is excluded. Smoking and fire have separate datasets, training and
weights; fusion occurs only during inference. Software only, no hardware installation
or enterprise integration. AGPL-3.0 is accepted, with source-sharing obligations.

Browser webcam / USB / RTSP / upload -> timestamped frames -> model adapters ->
association and context -> temporal decisions -> evidence and PostgreSQL -> Flask REST
-> React TypeScript dashboard. One live source initially; uploads are queued. Local
authenticated reviewers, UTC persistence and Asia/Karachi display.

Repository: AGENTS.md, README.md, LICENSE, pinned root/training/dev requirements,
.env.example, compose.yaml, docs/, configs/{application,inference},
datasets/<slug>/README.md, training/{common,<slug>/train.py}, models/{_pretrained,<slug>},
safesight/{contracts,model_loaders,inference,ingestion,storage,backend,worker}, migrations/,
frontend/, tools/, tests/{fixtures,unit,integration,e2e}, ai-context/{INDEX,nodes,decisions,graph.json},
docker/, artifacts/{runs,reports,media}. Generated assets and secrets are ignored.

## Dataset contracts

Every README states structure, formats, class IDs, labels, counts, collection and split rules.
Approximately 70/15/15 train/val/test by source video, scene and session BEFORE extraction.
Adjacent/augmented clips, duplicate downloads and synchronized views stay together.
Manifests contain sample/path/source/group/split/time/annotation provenance. Shared source
footage across tasks retains its partition. JPEG/PNG and decodable MP4 are supported.
User datasets are read-only; staging, caches and features live in artifacts/. Only missing
directories and READMEs are created in datasets/. Fixtures stay in tests/fixtures/.

YOLO uses images/{train,val,test}, labels/{train,val,test}, data.yaml, manifest.jsonl,
videos/{val,test}, events/{val,test}.jsonl. Labels are class_id x_center y_center width height,
normalized to [0,1]. Explicit empty negative labels are valid; missing labels are errors.
Video event labels evaluate behavior after fusion and smoothing. Body evaluation also needs
held-out videos. Annotation intervals and actor visibility must be explicit.

| Task | Ordered classes | Model, fallback and collection target |
|---|---|---|
| body_state | upright, seated, crouching_kneeling, deep_bend, lying_on_floor | MediaPipe landmarks/angles -> MLP 128/64 dropout .3; fallback 64-unit MLP. >=500 person examples/class and >=30 recording groups. Images plus per-image person-box/posture JSON. |
| phone_usage | person, phone | YOLO11s 960; fallback YOLO11n. >=3000 images; phone instances train/val/test >=500/100/100; >=20% hard negatives. Events distinguish using/carrying/nearby phones. |
| cigarette_smoking | person, cigarette, lighter, smoke | Independent YOLO11s 1280; fallback YOLO11n. >=4000 images; each object >=700/150/150 instances; >=50 hidden-cigarette smoking events in each val/test split. |
| entrance_guard | verified_entry, unverified_entry, no_entry, indeterminate | Frozen pretrained MobileNetV3-Small -> 2-layer LSTM hidden 128 dropout .3; fallback ResNet18 encoder. >=300 clips/class, >=50/class val and test, >=10 actor pairs, >=30 sessions. |
| fire_smoke | fire, smoke, person | Independent YOLO11s 640; fallback YOLO11n. >=3000 images; fire/smoke each >=500/100/100 instances; >=25% hard negatives. Smoke boxes describe appearance; event labels describe source. |

Counts are recommendations, not accuracy guarantees. Every class must occur in each split.
Entrance clips span up to 20 seconds at 5 FPS, 100 frames, aspect-preserving 224x224 input,
padding masks. Required procedure: stop, frisk, bag inspection if carrying a bag, permission,
crossing. Annotate phase intervals and bag presence. Negative examples skip individual steps.
No-entry covers waiting; indeterminate covers occlusion, incomplete clips and ambiguous identity.
Use a fixed entrance view, one lane and one entrant under inspection; reserve actors/sessions.
Keep approximately two seconds after crossing. Overlong/incomplete procedures are indeterminate.

## Training and quality

Independent commands:
`python tools/validate_dataset.py <slug>` and
`python training/<slug>/train.py --config training/<slug>/config.yaml`.
Every trainer supports --resume and --smoke. Shared training code lives only in training/common/.
Seed 42, validation first, reproducible logs/config/hash, optimizer/scheduler/RNG resume state.
Reject incompatible resumes. Auto-select usable CUDA, otherwise CPU with a diagnostic.
Memory-aware batching/accumulation must not silently change resolution, epochs or metric targets.

YOLO: 100 epochs, patience 20, AdamW .001, decay .0005, modest color/scale/flip augmentation,
no vertical flips; batches 4 phone/fire and 2 smoking; rare-class sampling only on train.
Smoking: mosaic .2 then disabled for last 10 epochs, no mixup, tiny-box-preserving augmentation,
full frames and derived person crops; report AP by size.
Body: 100 epochs, patience 15, AdamW .001/.0001, class weights, landmark jitter/visibility masks.
Guard: 60 epochs, patience 10, AdamW .001/.0001, frozen encoder/cache, weighted loss,
gradient clipping 1.0, consistent clip augmentation; never shuffle temporal order.
Pretrained feature extractors are used; new task heads are initialized for their classes.
Registered weights are explicitly downloaded and checksum verified. No dataset downloads.

Validator checks structure, provenance, label ranges, decode failures, empty files, missing
pairs, time bounds, sequence annotations, balance, split sizes, source diversity, exact and
perceptual duplicates, interval/scene leakage and cross-task partition conflicts. Confirmed
leakage/invalid structure fail; unresolved near-duplicates prevent production PASS.

Select best checkpoint on validation; replay val video through runtime logic; calibrate alert
thresholds to maximize recall subject to precision >=.90 with adequate support. No feasible
threshold means FAIL. Freeze decisions before one final test evaluation. No test-driven tuning.
Events match one-to-one by type/person/location/time; duplicate alerts count as false positives.

| Task | Model target | Test alert target |
|---|---|---|
| body | macro F1 >=.85 | each unsafe class precision >=.90, recall >=.75 |
| phone | phone AP50 >=.70; report mAP50-95 | precision >=.90, recall >=.80 |
| smoking | cigarette/lighter AP50 >=.35, smoke >=.60 | precision >=.90, recall >=.70; hidden recall >=.60 |
| guard | macro F1 >=.80 | unverified precision >=.90/recall >=.80; verified precision >=.95 |
| fire | fire and smoke AP50 >=.70 | each hazard precision/recall >=.90 |

Report support, confusion, PR curves, delay, false alerts/camera-hour, grouped confidence intervals.
PASS requires real data, >=50 positive/negative opportunities per alert category and >=5 evaluation
groups. Missing support/undefined metrics cannot pass. Diagnose missing data, imbalance, leakage
and suspected label noise without pretending hypotheses are measured facts.

Weights/cards live under models/<slug>/versions/<run_id>. Cards record schema, loader, architecture,
classes, artifact hashes, preprocessing, input/sequence specs, thresholds, temporal policy, metrics,
support, gate reasons, dataset/config hashes, seed/date/revision/versions and synthetic status.
Only passing real runs activate root model_card.json. Failed artifacts are available in explicit
evaluation mode. Loaders read MODELS_ROOT only, never download. Missing models are degraded,
never all-clear. Swaps within supported adapters require files/config and restart, no pipeline edits.

## Runtime and application

Default sampling 5 FPS; phone/smoking 3-of-5; body also needs deep_bend 3 seconds or lying 1 second;
fire 2-of-3; entrance waits for completed crossing context. Timestamp gaps reset state; unknown
frames do not imply safety. Merge ongoing events, cooldown 10 seconds. Location posture overrides.
Shared frozen pose supplies hand/mouth context without depending on the trained body classifier.
Hidden smoking requires multiple compatible cues; lighter alone is insufficient. Smoke fusion
uses flame, extent/growth, persistence and person context; proximity alone cannot establish tobacco.
Strong fire is never suppressed by smoking; conflicts retain an uncertain alert.

Browser: permission-based getUserMedia, preview, JPEG REST upload <=5 FPS, no audio, authenticated
sequence numbers, payload limits, backpressure and 2-second pending queue. Require localhost/HTTPS.
Separate worker, PostgreSQL leases/state and bounded filesystem spool; live jobs take priority.
Uploads preserve media timestamps; absent capture time stays unknown. Save JPEG and 5-second pre/post
clips; entrance keeps complete window. Evidence states pending/ready/failed; idempotent persistence.

PostgreSQL UUID schema: users, locations, sources, processing_jobs, model_versions, incidents,
incident_predictions, evidence, incident_reviews. Foreign keys, indexed filters, append-only reviews.
Review status pending/confirmed/dismissed is distinct from model uncertainty. Alembic migrations.
API /api/v1: auth/login/logout/me; locations; sources/start/stop/frames; uploads; jobs; incidents
with type/date/location/status pagination; incident detail/review; evidence with range support;
models; health/live and health/ready. Session/CSRF, consistent errors, safe paths and trusted RTSP hosts.
React dashboard: webcam, uploads, health, filters, evidence and review, 2-second polling, honest
empty/error/uncertain/evaluation states. No fabricated records or metrics.

## Dependencies, context and milestones

Pinned root closure covers training/backend/inference. Training subset independently installs;
overlap pins agree. Separate dev pins and exact npm lock. One OpenCV distribution. Fresh venv install,
pip check/import/model operations for both sets. Document matching official PyTorch CPU/CUDA commands.

AI context nodes have id/type/status/links frontmatter and what/why/how/I-O/gotchas bodies. INDEX is
entry point; numbered ADRs record context/options/decision/consequences. Graph generator rejects
duplicate IDs, malformed metadata, broken links and unreachable nodes. --check detects stale graph.
Every code change updates context; deviations require ADR plus user explanation.

M0 scaffold/dependencies/context: fresh installs/imports/graph. M1 dataset docs/validator/fixtures:
bad labels/media, valid negatives, leaks, read-only behavior. M2 five trainers: one-epoch smoke,
resume/calibration failures/reports/CPU independence. M3 loaders/fusion: swaps, missing models,
preprocessing parity, hidden cues, conflicts/tracks/gaps. M4 migrations: empty PostgreSQL/constraints/
review history/idempotency. M5 backend: uploads/frames/backpressure/recovery/evidence/reviews.
M6 dashboard: build/browser capture denial/reconnect/empty/error/filter/review. M7 Docker/README:
startup/persistence/health/restart. M8 actual synthetic models plus deterministic adapter integration
tests through worker/database/API/dashboard; measure tested hardware only. Update context each step.

Smoke artifacts stay under tests/fixtures and require evaluation mode. Synthetic body landmarks
exercise classifier training; real pose extraction is separately checked on blank imagery. Synthetic
accuracy cannot establish real quality. Random one-epoch models are not required to detect scripted
violations; deterministic adapters separately verify decision/persistence behavior.

## Risks and completion

Data quality/coverage can require retraining. Fully hidden cues cannot be inferred reliably.
Guard behavior cannot prove inspection thoroughness or absence of contraband. Body policies need
task exceptions. Smoke requires dust/steam/welding negatives. CPU throughput remains hardware-dependent.
Retain AGPL and pretrained/dataset licenses. Surface missing models, dropped frames, full disks and faults.
Final report separates verified software from unverified real accuracy/GPU/camera conditions.
Done: drop data, validate, independently train, receive honest gate/card/artifacts and load through
config into backend/dashboard without pipeline edits; context graph passes.

## Approved update: automatic partitions and backend modules

The user approved resource-based backend separation and requested automatic splits at training time. ADR 0005 supersedes manual input partitioning: flat datasets are staged by source/session group under artifacts; existing splits remain accepted. Full evaluation and quality gates remain required. See AUTOMATIC_SPLITS.md.

## Approved update: colocated configs and model sharing

ADR 0006 moves recipes beside train.py and selects shared-drive model bundles with checked export/fetch. Runtime packages and CI remain.
