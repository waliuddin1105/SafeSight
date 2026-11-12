# body_state dataset
## Recommended input: unsplit data

You do not need to divide files into train/val/test manually. Put media and labels
in flat images/labels (or clips/annotations) directories, omit split from manifest
rows, and supply events.jsonl with flat videos/ paths. Validation/training generate
reproducible source-group partitions under artifacts without modifying your data.
See [automatic splitting](../../docs/AUTOMATIC_SPLITS.md). The split layouts below
describe the generated format and remain accepted for existing datasets.


## Classes

- 0: upright
- 1: seated
- 2: crouching_kneeling
- 3: deep_bend
- 4: lying_on_floor

## Required layout

```text
images/{train,val,test}/*.jpg
annotations/{train,val,test}/*.json
manifest.jsonl
videos/{val,test}/*.mp4
events/{val,test}.jsonl
```

JPEG/PNG images and decodable MP4 recordings are accepted. Keep source timestamps. Each media file needs a manifest record and annotation.

## Provenance

One JSON object per line in manifest.jsonl:

```json
{
  "sample_id": "cameraA_session01_0001",
  "path": "images/train/sample01.jpg",
  "annotation": "annotations/train/sample01.json",
  "source_id": "original-video-sha256-or-stable-id",
  "group_id": "cameraA_scene1_session01",
  "split": "train",
  "start": 0.0,
  "end": 0.0
}
```

## Labels

One JSON file per image, normalized xyxy boxes:

```json
{
  "people": [
    {
      "person_id": "worker1",
      "box": [
        0.1,
        0.1,
        0.8,
        0.9
      ],
      "label": "upright"
    }
  ]
}
```

Label visible posture; low visibility is unknown at inference. Inline landmarks are reserved for synthetic fixtures. Deep bend for 3 seconds or lying on floor for 1 second alerts by default.

## Event evaluation

Each line in events/val.jsonl or events/test.jsonl describes one whole video, including negatives with events: []. Boxes identify actor/hazard using normalized xyxy. Track IDs are annotation-local.

```json
{
  "video": "videos/val/example.mp4",
  "source_id": "eval-original-01",
  "group_id": "eval-session01",
  "events": [
    {
      "subtype": "deep_bend",
      "start": 2.0,
      "end": 6.0,
      "track_id": "person1",
      "box": [
        0.1,
        0.1,
        0.8,
        0.9
      ],
      "hidden_cigarette": false
    }
  ]
}
```

Subtypes: deep_bend, lying_on_floor. Tobacco smoke is boxed as smoke but is not hazardous_smoke truth. Mark hidden_cigarette=true for occluded smoking. Include idle phones, eating/drinking and face touching as negatives.

## Counts and splits

Recommended: 500 person examples/class, >=30 sessions. These are not accuracy guarantees. Quality PASS needs >=50 positive events and >=50 negative evaluation videos/category and >=5 evaluation groups.

Automatic splitting assigns approximately 70/15/15 by ORIGINAL source video, scene and session; supply consistent provenance before extraction. Never randomly split frames/windows. Keep adjacent clips, synchronized views, augmentations and duplicate downloads together. Shared footage across tasks keeps the same partition. Every class must occur in each split; aim below 5:1 imbalance. Test is untouched until model/thresholds are frozen.

```text
python tools/validate_dataset.py body_state
python training/body_state/train.py --config training/body_state/config.yaml
```

Validator/trainer never write here. Derived caches/crops/reports go to artifacts/. Synthetic fixtures only belong in tests/fixtures/.
