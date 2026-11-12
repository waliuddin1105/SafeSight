# Automatic dataset splitting

Place annotated data in the use-case directory without train/val/test folders:

```text
datasets/<slug>/
  images/                 # clips/ for entrance_guard
  labels/                 # annotations/ JSON for body_state and entrance_guard
  manifest.jsonl
  data.yaml               # YOLO only: ordered names; split paths generated
  videos/                 # non-guard behavioral evaluation recordings
  events.jsonl            # annotations for those recordings
```

Manifest rows use the existing fields but **omit split**. For example:

```json
{"sample_id":"cameraA_001","path":"images/cameraA_001.jpg","annotation":"labels/cameraA_001.txt","source_id":"original-video-01","group_id":"cameraA-session01","start":1.0,"end":1.0}
```

Keep the existing class and annotation formats in each dataset README. Event records
use the existing event format with unsplit paths such as videos/recording01.mp4.
Group IDs must identify the true recording scene/session; all samples from a source
video must share one group. Use the same IDs across smoking/fire datasets sharing
footage. Missing provenance cannot safely be replaced by image filenames.

Run the ordinary validator or training command. Both materialize approximately
70/15/15 train/validation/test using a deterministic hash of group ID and seed.
No manual partitioning or movement is necessary. The validator uses seed 42 by
default; pass --seed to match a different training configuration. Training YAML
accepts split_ratios (default [0.70, 0.15, 0.15]). Use identical seeds/ratios across
tasks to preserve shared-source partitions.

Generated copies and split_plan.json live in artifacts/dataset-splits/<slug>/<hash>/.
Original files are read-only. Budget additional disk space for generated copies.
The plan records group assignments and file checksums; unchanged inputs reuse it.
Changing input data creates a new version. Resume rejects changed fingerprints.
Existing datasets already divided into train/val/test remain supported. Mixing
manual and unsplit manifest rows is rejected.

Ratios are approximate because sessions stay intact. With too few independent
groups, a partition/class can be absent; validation fails visibly. Collect more
independent sessions rather than reroll seeds until test scores improve. Fix the
seed before inspecting test results. The test partition is reused across reruns
and is not used for training, checkpoint selection or threshold calibration.

Automatic partitioning does not supply missing labels or event footage. The full
existing validation and quality requirements still apply. In particular, videos
and events assigned to validation/test are used for temporal alert evaluation;
training-assigned videos do not enter those measurements.
