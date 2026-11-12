"""Deterministic artificial data for software execution checks, never real accuracy."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
import yaml

from safesight.config import ROOT
from safesight.contracts import CLASSES, YOLO_SLUGS
from safesight.ingestion.video import write_video


def generate(slug: str, root: Path | None = None) -> Path:
    """Create a small, distinctly marked dataset only within tests/fixtures."""
    base = (root or ROOT / "tests/fixtures/datasets" / slug).resolve()
    if not base.is_relative_to((ROOT / "tests/fixtures").resolve()):
        raise ValueError("Synthetic fixtures must be inside tests/fixtures")
    marker = base / "fixture.json"
    if marker.exists():
        return base
    base.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(42 + list(CLASSES).index(slug))
    records = []
    for split, repetitions in (("train", 3), ("val", 1), ("test", 1)):
        for class_id, label in enumerate(CLASSES[slug]):
            for repetition in range(repetitions):
                name = f"{split}_{class_id}_{repetition}"
                image = Image.fromarray(rng.integers(0, 140, (128, 128, 3), dtype=np.uint8))
                draw = ImageDraw.Draw(image)
                draw.rectangle((25, 13, 100, 115), outline=(255, 180, class_id * 40), width=4)
                folder = "clips" if slug == "entrance_guard" else "images"
                extension = "mp4" if slug == "entrance_guard" else "jpg"
                path = base / folder / split / f"{name}.{extension}"
                path.parent.mkdir(parents=True, exist_ok=True)
                annotation = (
                    base
                    / ("labels" if slug in YOLO_SLUGS else "annotations")
                    / split
                    / f"{name}.{'txt' if slug in YOLO_SLUGS else 'json'}"
                )
                annotation.parent.mkdir(parents=True, exist_ok=True)
                if slug in YOLO_SLUGS:
                    image.save(path)
                    annotation.write_text(f"{class_id} 0.5 0.5 0.5 0.75\n", encoding="utf-8")
                elif slug == "body_state":
                    image.save(path)
                    landmarks = rng.normal(0, 0.02, (33, 4))
                    landmarks[:, :2] += [0.5, 0.5]
                    landmarks[:, 3] = 1
                    landmarks[11, :2], landmarks[12, :2] = [0.35, 0.25], [0.65, 0.25]
                    landmarks[23, :2], landmarks[24, :2] = [0.4, 0.55], [0.6, 0.55]
                    landmarks[25:29, 1] = 0.8 if class_id == 0 else 0.6
                    landmarks[:, 0] += class_id * 0.03
                    if class_id == 4:
                        landmarks[:, [0, 1]] = landmarks[:, [1, 0]]
                    annotation.write_text(
                        json.dumps(
                            {
                                "people": [
                                    {
                                        "person_id": "person1",
                                        "label": label,
                                        "box": [0.1, 0.1, 0.9, 0.95],
                                        "landmarks": landmarks.tolist(),
                                    }
                                ]
                            }
                        ),
                        encoding="utf-8",
                    )
                else:
                    images = [np.roll(np.asarray(image), shift, axis=1) for shift in range(10)]
                    write_video(path, images, 5)
                    phases = [
                        {"name": name, "start": start, "end": end}
                        for name, start, end in [
                            ("stop", 0, 0.2),
                            ("frisk", 0.2, 0.6),
                            ("bag_inspection", 0.6, 1),
                            ("permission", 1, 1.2),
                            ("crossing", 1.2, 1.6),
                        ]
                    ]
                    if label == "unverified_entry":
                        phases = [phases[0], phases[-1]]
                    if label in ("no_entry", "indeterminate"):
                        phases = []
                    annotation.write_text(
                        json.dumps(
                            {
                                "label": label,
                                "entrant_id": "person1",
                                "bag_present": True,
                                "fully_visible": label != "indeterminate",
                                "crossing_time": 1.4 if label.endswith("entry") and label != "no_entry" else None,
                                "roi": [0, 0, 1, 1],
                                "phases": phases,
                            }
                        ),
                        encoding="utf-8",
                    )
                records.append(
                    {
                        "sample_id": name,
                        "path": path.relative_to(base).as_posix(),
                        "annotation": annotation.relative_to(base).as_posix(),
                        "source_id": f"{slug}_{name}",
                        "group_id": f"{slug}_{name}",
                        "split": split,
                        "start": 0,
                        "end": 2 if slug == "entrance_guard" else 0,
                        "synthetic": True,
                    }
                )
        if slug != "entrance_guard" and split != "train":
            event_records = []
            for index in range(2):
                video = base / "videos" / split / f"evaluation_{index}.mp4"
                image = rng.integers(0, 255, (128, 128, 3), dtype=np.uint8)
                write_video(video, [np.roll(image, t, axis=0) for t in range(10)])
                subtype = {
                    "body_state": "deep_bend",
                    "phone_usage": "phone_usage",
                    "cigarette_smoking": "smoking",
                    "fire_smoke": "fire",
                }[slug]
                event_records.append(
                    {
                        "video": video.relative_to(base).as_posix(),
                        "source_id": f"{slug}_{split}_eval{index}",
                        "group_id": f"{slug}_{split}_eval{index}",
                        "events": [
                            {
                                "subtype": subtype,
                                "start": 0.2,
                                "end": 1.8,
                                "track_id": "person1",
                                "box": [0.1, 0.1, 0.9, 0.9],
                                "hidden_cigarette": True,
                            }
                        ]
                        if index == 0
                        else [],
                    }
                )
            (base / "events").mkdir(exist_ok=True)
            (base / "events" / f"{split}.jsonl").write_text(
                "\n".join(json.dumps(r) for r in event_records) + "\n", encoding="utf-8"
            )
    (base / "manifest.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    if slug in YOLO_SLUGS:
        (base / "data.yaml").write_text(
            yaml.safe_dump(
                {
                    "path": ".",
                    "train": "images/train",
                    "val": "images/val",
                    "test": "images/test",
                    "names": CLASSES[slug],
                }
            ),
            encoding="utf-8",
        )
    marker.write_text(
        json.dumps({"synthetic": True, "seed": 42, "purpose": "software execution only"}), encoding="utf-8"
    )
    return base
