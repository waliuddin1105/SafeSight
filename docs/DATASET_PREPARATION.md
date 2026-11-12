# Prepare datasets on the training machine

The preparation script supports Python 3.11 on Windows, Linux and macOS, including
compatible cloud notebooks/VMs. It does not need a GPU and never starts training.
Install the project's training requirements on that machine first.

## One command for the four public sources

From the SafeSight project root:

```text
python tools/prepare_datasets.py
```

This selects body_state, phone_usage, cigarette_smoking and fire_smoke. Guard verification
is excluded. Preview sources and requirements without downloading anything:

```text
python tools/prepare_datasets.py all --plan
```

Prepare only one task:

```text
python tools/prepare_datasets.py cigarette_smoking
```

Data is extracted into datasets/SLUG/_sources/SOURCE-HASH/. Archives are cached under
datasets/_downloads/SLUG/. preparation.json in each task folder records attribution,
hashes, inventory and readiness. The summary is artifacts/dataset-preparation/report.json.
Repeated runs reuse complete archives/extractions; interrupted transfers/extractions can
resume when provider validators and source identity allow it. Changed files are preserved.

For another disk, pass portable paths suitable for that device:

```text
python tools/prepare_datasets.py all --datasets-root /mnt/data/SafeSight/datasets --cache-root /mnt/data/SafeSight/downloads
```

On Windows, use paths such as F:/SafeSightData/datasets. No paths are tied to the current
developer's PC. Training configurations for READY native bundles are generated under
artifacts/dataset-preparation/ with the actual destination set, and the exact training
command is printed. Downloading, extraction and native installation all check free space.

## Provider access

Source definitions, licenses, expected hashes and known annotation gaps are in
configs/dataset_sources.yaml. Check the original publishers' terms before use.

- POLAR uses the pinned public mirror archive/hash, with the original release cited.
- FPI-Det's published Drive link can require login/confirmation. If it does, obtain an
  authorized ZIP/TAR export through the authors' link and use --archive. The script does
  not bypass login or consent pages.
- Smoking_person uses the official Roboflow export API for version 3. Set ROBOFLOW_API_KEY
  in .env once, or provide an already downloaded authorized archive.
- D-Fire uses the publisher-linked Kaggle export. If anonymous download is denied, set
  KAGGLE_USERNAME and KAGGLE_KEY in .env or supply an authorized archive.

The four optional *_ARCHIVE_URL environment variables in .env.example let you use a
provider-authorized direct archive URL. Private URLs/keys are not written to receipts
or printed in error reports. Replacing an official URL means its pinned hash no longer
applies; the fetched file's actual SHA-256 is still recorded.

```text
python tools/prepare_datasets.py phone_usage --archive phone_usage=/path/to/authorized-export.zip
```

ZIP and TAR are supported; RAR requires exporting/extracting and repacking to ZIP/TAR.
No dataset-supplied scripts are executed. Archive links, unsafe paths, duplicate aliases
and oversized extractions are rejected.

## What READY means

The public datasets identified so far do not cover our complete approved taxonomy and
temporal evaluation requirements. The downloader cannot create missing ground truth.
It preserves original annotations and reports DOWNLOADED_NEEDS_ANNOTATIONS, including:

- Body: review bending/deep-bend and lying/lying-on-floor semantics.
- Phone: head boxes cannot replace required person boxes.
- Smoking: lighter annotations and hidden-cigarette event coverage are missing.
- Fire/smoke: required person annotations and smoke-source event labels need completion.
- All: source-video/scene provenance and genuine held-out behavioral videos need auditing.

Missing classes are not filled using automatic predictions, and frames are not randomly
repartitioned to hide missing provenance. Current training validation remains strict.

For automatic installation into the canonical images/labels/annotations/videos/events
layout, supply a reviewed SafeSight-native ZIP/TAR bundle with the required manifest and
annotations from datasets/SLUG/README.md. The archive can contain that layout at its root
or in a SLUG subfolder. The script validates it before copying, refuses conflicting user
files, publishes the manifest last and validates the installed result again.

Exit 0: every selected dataset is structurally READY for its trainer.
Exit 2: one or more sources are blocked or need annotations/review; inspect the report.
READY is not a model quality PASS or an accuracy claim. Near-duplicate/source warnings
remain in the validation result and can prevent the model's quality gate from passing.

## Performance expectations

An 80% score cannot be inferred from a dataset's name or size. Use held-out subject/scene
splits representative of the target factory cameras. For body_state, evaluate macro F1
and unsafe-state recall; for detectors, evaluate per-class AP, precision and recall;
for alerts, evaluate complete events and false alarms per camera-hour. Existing target
precision remains 0.90; this preparation tool does not lower training quality gates.
Additional compute changes feasible model size and training speed. It does not establish
the correctness/completeness of labels, fix domain shift, or establish hidden-action recall.

No bulk source download or training was executed on the current development PC. Software
checks use local synthetic archives and an HTTP test server only.

Reviewed native bundles also accept unsplit layouts; see [automatic splits](AUTOMATIC_SPLITS.md). Their readiness checks stage partitions outside datasets.
