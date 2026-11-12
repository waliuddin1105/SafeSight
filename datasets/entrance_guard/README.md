# entrance_guard dataset
## Recommended input: unsplit data

You do not need to divide files into train/val/test manually. Put media and labels
in flat images/labels (or clips/annotations) directories, omit split from manifest
rows, and supply events.jsonl with flat videos/ paths. Validation/training generate
reproducible source-group partitions under artifacts without modifying your data.
See [automatic splitting](../../docs/AUTOMATIC_SPLITS.md). The split layouts below
describe the generated format and remain accepted for existing datasets.


## Classes

- 0: verified_entry
- 1: unverified_entry
- 2: no_entry
- 3: indeterminate

## Required layout

```text
clips/{train,val,test}/*.mp4
annotations/{train,val,test}/*.json
manifest.jsonl
```

JPEG/PNG images and decodable MP4 recordings are accepted. Keep source timestamps. Each media file needs a manifest record and annotation.

## Provenance

One JSON object per line in manifest.jsonl:

```json
{
  "sample_id": "cameraA_session01_0001",
  "path": "clips/train/sample01.mp4",
  "annotation": "annotations/train/sample01.json",
  "source_id": "original-video-sha256-or-stable-id",
  "group_id": "cameraA_scene1_session01",
  "split": "train",
  "start": 0.0,
  "end": 20.0
}
```

## Labels and collection

20-second clips sampled at 5 FPS, with complete procedure and 2 seconds after crossing. Fixed view shows guard, entrant, bags, inspection area and crossing line. One entrant per lane. Reserve actors/sessions for evaluation.

```json
{
  "label": "verified_entry",
  "entrant_id": "actor02",
  "bag_present": true,
  "fully_visible": true,
  "crossing_time": 16.0,
  "roi": [
    0,
    0,
    1,
    1
  ],
  "phases": [
    {
      "name": "stop",
      "start": 0,
      "end": 2
    },
    {
      "name": "frisk",
      "start": 2,
      "end": 8
    },
    {
      "name": "bag_inspection",
      "start": 8,
      "end": 12
    },
    {
      "name": "permission",
      "start": 12,
      "end": 14
    },
    {
      "name": "crossing",
      "start": 14,
      "end": 17
    }
  ]
}
```

Order: stop, frisk, applicable bag inspection, permission, crossing. Nonoverlapping phase intervals. Null crossing_time for no_entry/indeterminate without crossing. Unverified examples skip mandatory steps; no_entry covers waiting; indeterminate covers occlusion, crowding and incomplete/overlong clips. Video cannot establish inspection thoroughness.

## Counts and splits

Recommended: 300 clips/class, including >=50/class in each val/test split; >=10 actor pairs and >=30 sessions. These are not accuracy guarantees. Quality PASS needs >=50 positive events and >=50 negative evaluation videos/category and >=5 evaluation groups.

Automatic splitting assigns approximately 70/15/15 by ORIGINAL source video, scene and session; supply consistent provenance before extraction. Never randomly split frames/windows. Keep adjacent clips, synchronized views, augmentations and duplicate downloads together. Shared footage across tasks keeps the same partition. Every class must occur in each split; aim below 5:1 imbalance. Test is untouched until model/thresholds are frozen.

```text
python tools/validate_dataset.py entrance_guard
python training/entrance_guard/train.py --config training/entrance_guard/config.yaml
```

Validator/trainer never write here. Derived caches/crops/reports go to artifacts/. Synthetic fixtures only belong in tests/fixtures/.
