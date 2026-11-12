# M0-M7 delivery and verification

This pass implements M0 through M7. Training entrypoints were not executed, per the
user's instruction. M8 and real model training are outside this pass.

| Milestone | Implementation | Verification |
|---|---|---|
| M0 | Project structure, configuration, pinned CPU dependencies, context tooling, license | Existing independent environment installs; imports/pip checks; release contract checks |
| M1 | Five collection contracts, grouped provenance, media/label/event validation, fixture generator | Corrupt/empty files, invalid labels, duplicate/source leakage and read-only checks |
| M2 | Independent trainers, checkpoint/resume, validation calibration, test reports, size AP, explicit gates | Syntax, shared contracts, metric/gate tests and entrypoint isolation; no training executed |
| M3 | Card loaders, shared crop/preprocessing, artifact policy, fusion qualification, temporal logic | Model replacement, hash rejection, crop parity, N-of-M/gaps, strong-fire preservation, recovery codec |
| M4 | PostgreSQL schema and two reversible migrations | Fresh database upgrade/downgrade/upgrade; relational application integration |
| M5 | Auth/CSRF, source controls, bounded frame queue, upload jobs, evidence and reviews | PostgreSQL tests, duplicate rejection, worker restart/pending clip recovery, evidence/filter/review flow |
| M6 | React capture/upload/incident review dashboard and worker/fusion health | TypeScript production build; browser sign-in, filters, permission denial, capture and reconnect |
| M7 | Docker image/Compose, setup and operation docs, CI without training | Source/Compose contract checks; local Docker runtime unavailable |

The untrained inference fixture generator creates random detector weights and fixed
classifier logits solely for software checks. Every artifact is marked synthetic and
fails production qualification. It never calls a trainer or optimizer.

Deployment readiness still requires Docker runtime checks on a Docker-capable host.
Real safety performance, target GPU throughput and physical USB/RTSP behavior require
the user's data/hardware. These are verification limits, not claimed measurements.
