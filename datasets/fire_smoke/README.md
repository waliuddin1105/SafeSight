# fire_smoke dataset
## Recommended input: unsplit data

You do not need to divide files into train/val/test manually. Put media and labels
in flat images/labels (or clips/annotations) directories, omit split from manifest
rows, and supply events.jsonl with flat videos/ paths. Validation/training generate
reproducible source-group partitions under artifacts without modifying your data.
See [automatic splitting](../../docs/AUTOMATIC_SPLITS.md). The split layouts below
describe the generated format and remain accepted for existing datasets.


## Classes

- 0: fire
- 1: smoke
- 2: person

## Required layout

```text
images/{train,val,test}/*.jpg
labels/{train,val,test}/*.txt
manifest.jsonl
data.yaml
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
  "annotation": "labels/train/sample01.txt",
  "source_id": "original-video-sha256-or-stable-id",
  "group_id": "cameraA_scene1_session01",
  "split": "train",
  "start": 0.0,
  "end": 0.0
}
```

## Labels

Each line: zero-based class_id x_center y_center width height, normalized to [0,1]. Positive width/height; box entirely inside image. A verified negative has an explicit empty .txt; missing labels are errors. Label every visible target, including people.

```text
0 0.5 0.5 0.4 0.8
```

Use this data.yaml:

```yaml
path: .
train: images/train
val: images/val
test: images/test
names:
  0: fire
  1: smoke
  2: person
```

## Event evaluation

Each line in events/val.jsonl or events/test.jsonl describes one whole video, including negatives with events: []. Boxes identify actor/hazard using normalized xyxy. Track IDs are annotation-local.

```json
{
  "video": "videos/val/example.mp4",
  "source_id": "eval-original-01",
  "group_id": "eval-session01",
  "events": [
    {
      "subtype": "fire",
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

Subtypes: fire, hazardous_smoke, uncertain_smoke. Tobacco smoke is boxed as smoke but is not hazardous_smoke truth. Mark hidden_cigarette=true for occluded smoking. Include idle phones, eating/drinking and face touching as negatives.

## Counts and splits

Recommended: 3000 images; fire/smoke each >=500/100/100 instances; >=25% negatives including steam, dust, reflections and tobacco smoke. These are not accuracy guarantees. Quality PASS needs >=50 positive events and >=50 negative evaluation videos/category and >=5 evaluation groups.

Automatic splitting assigns approximately 70/15/15 by ORIGINAL source video, scene and session; supply consistent provenance before extraction. Never randomly split frames/windows. Keep adjacent clips, synchronized views, augmentations and duplicate downloads together. Shared footage across tasks keeps the same partition. Every class must occur in each split; aim below 5:1 imbalance. Test is untouched until model/thresholds are frozen.

```text
python tools/validate_dataset.py fire_smoke
python training/fire_smoke/train.py --config training/fire_smoke/config.yaml
```

Validator/trainer never write here. Derived caches/crops/reports go to artifacts/. Synthetic fixtures only belong in tests/fixtures/.

Image-based trainers do not require event videos. They remain evaluation-only until separate qualification; entrance_guard always requires ordered clips. See docs/IMPROVEMENTS.md.
