---
id: dependencies
type: component
status: implemented
links:
- architecture
- quality
---
# Dependencies

## What, why and how

Python 3.11 is the supported baseline. Root/training requirements are separately installable pinned closures with identical overlap; only one OpenCV distribution is used.

## Inputs and outputs

Input: requirements.in files and optional matching CUDA installation. Output: isolated CPU or CUDA environments; tools/verify_environment.py checks imports and operations.

## Gotchas

MediaPipe .10.31 has an incorrect internal wheel tag; actual Windows Tasks execution and standard pip check pass. CUDA and Linux Docker runtime require host-specific verification.

Third-party Ultralytics settings are initialized under artifacts/library-config. Registered pretrained-asset download implementation lives in training/common/assets.py; tools/fetch_pretrained.py is its CLI wrapper. Runtime loaders never download assets.
