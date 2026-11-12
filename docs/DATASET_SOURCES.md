# Public dataset sourcing review

Reviewed 2026-11-12 for body_state, phone_usage, cigarette_smoking and fire_smoke.
Guard verification is excluded. No datasets have been downloaded or installed.
No training has been executed. Existing dataset contents remain unchanged.

## Current blockers

- C: has approximately 0.25 GB free. F: has approximately 92 GB free. A download
  destination is awaiting the user's choice. Download size is not the same as required
  working space: archives, extracted files and training staging can coexist.
- Available public annotations do not establish complete coverage of SafeSight's exact
  classes, source-group splits and temporal event ground truth. The annotation policy
  is awaiting the user's choice. Missing labels must never be silently treated as negatives.
- These are promising candidates, not a benchmark-proven ranking or ready-to-run installation.

## Shortlist

| Task | Candidate and primary source | Useful coverage | Gaps before the current trainer can run |
|---|---|---|---|
| body_state | [POLAR official release](https://data.mendeley.com/datasets/hvnsh7rwz7/1) | Published posture labels include standing, sitting, squatting, bending and lying; official release states CC BY 4.0. | Inspect actual person annotations and source metadata. Bending is not automatically deep_bend; lying is not automatically lying_on_floor. Temporal event videos are still required. |
| phone_usage | [FPI-Det authors' repository](https://github.com/KvCgRv/FPI-Det) | Surveillance-oriented phone-use collection; authors document head/phone boxes and an additional classification task, with MIT licensing. | Head boxes cannot become person boxes. Obtain the original archive through its published access route, inspect annotations/provenance, and supply missing body boxes and temporal events if retaining the approved classes. |
| cigarette_smoking | [Smoking_person publisher page](https://universe.roboflow.com/visionwork/smoking_person) | Published classes Person, Cigarette, Smoke and Vape; CC BY 4.0. Multiple export versions are listed. | No lighter class. Verify export access, annotation completeness, unaugmented source groups and video-event labels. Hidden-cigarette capability cannot be established from ordinary image boxes alone. |
| fire_smoke | [D-Fire authors' repository](https://github.com/gaia-solutions-on-demand/DFireDataset) | YOLO fire/smoke boxes, negative images and links to surveillance footage. [Collection license](https://github.com/gaia-solutions-on-demand/DFireDataset/blob/master/LICENSE) is CC0, with upstream-image terms noted by the authors. | No person class. Verify original-source grouping rather than blindly accepting supplied splits. Surveillance videos need inspected temporal/hazard-source annotations for this pipeline. |

## Other leads checked

- [test4 smoking collection](https://universe.roboflow.com/-echdb/test4-8mvvh)
  lists cigarette/lighter/smoke-related classes, but the inspected page has zero dataset
  versions. A class list and preview do not establish a usable annotated export.
- CHP's paper points to https://github.com/wuyou3474/CHPDataset, which returned 404
  during this review. Do not select it on the assumption that the original download works.
- A [POLAR mirror](https://huggingface.co/datasets/sayantan47/POLAR-Posture-Level-Action-Recognition-Dataset)
  lists a roughly 3.18 GB archive. Prefer the original release and verify any mirror
  against the original license and content before use.
- FPI-Det's published Google Drive download currently exposes a sign-in page to the
  web reader. No credentials have been requested, supplied or bypassed.

## Preparation requirements after decisions

1. Resolve a storage destination with sufficient headroom. Keep dataset paths under
   configuration; external storage can be used without changing model pipeline code.
2. Download original, unaugmented exports when possible and retain their licenses,
   attribution, version, URL, file hashes and original annotations.
3. Inspect class meaning/completeness and samples before applying a mapping.
4. Group by verified original video/scene/session, then split. Flag unknown provenance;
   do not invent independent source IDs to make leakage checks pass.
5. Convert labels and prepare manifests only for verified mappings. Track automatic
   drafts separately if the user chooses them; they require review.
6. Supply genuine held-out event footage and annotations. Stitched still images are
   not a substitute for behavioral video evaluation.
7. Run dataset validation, report counts and unresolved gaps, and leave training for the user.

## Portable acquisition update

The user clarified that data will be downloaded on the future training computer.
Use tools/prepare_datasets.py; see docs/DATASET_PREPARATION.md. The local disk snapshot
above is historical, not a requirement on that device. Annotation gaps remain unchanged.
