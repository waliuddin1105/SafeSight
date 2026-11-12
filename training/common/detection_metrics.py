"""Measured object-size AP50, with absent categories reported as undefined."""

from __future__ import annotations

import numpy as np
from PIL import Image

from safesight.inference.engine import iou
from training.common.datasets import jsonl


def size_ap(records: list[dict], classes: list[str]) -> dict:
    """101-point interpolated AP50; ignore matches to GT outside the size bin."""
    result = {}
    for name, lower, upper in (("small", 0, 32**2), ("medium", 32**2, 96**2), ("large", 96**2, float("inf"))):
        by_class = {}
        for class_id, label in enumerate(classes):
            ranked, positive = [], 0
            for record in records:
                area = record["width"] * record["height"]
                targets = [t for t in record["targets"] if t["class_id"] == class_id]
                in_bin = {
                    i
                    for i, t in enumerate(targets)
                    if lower <= (t["box"][2] - t["box"][0]) * (t["box"][3] - t["box"][1]) * area < upper
                }
                positive += len(in_bin)
                used = set()
                for prediction in sorted(record["predictions"], key=lambda p: p["score"], reverse=True):
                    if prediction["class_id"] != class_id:
                        continue
                    matches = [(iou(prediction["box"], t["box"]), i) for i, t in enumerate(targets) if i not in used]
                    best, index = max(matches, default=(0, -1))
                    if best >= 0.5:
                        used.add(index)
                        if index in in_bin:
                            ranked.append((prediction["score"], 1))
                    else:
                        box = prediction["box"]
                        if lower <= (box[2] - box[0]) * (box[3] - box[1]) * area < upper:
                            ranked.append((prediction["score"], 0))
            ranked.sort(reverse=True)
            tp = np.cumsum([p[1] for p in ranked])
            precision = tp / np.arange(1, len(ranked) + 1) if ranked else np.array([])
            recall = tp / positive if positive else np.array([])
            ap = (
                float(np.mean([precision[recall >= r].max(initial=0) for r in np.linspace(0, 1, 101)]))
                if positive
                else None
            )
            by_class[label] = {"ap50": ap, "ground_truth_instances": positive}
        defined = [v["ap50"] for v in by_class.values() if v["ap50"] is not None]
        result[name] = {"ap50": float(np.mean(defined)) if defined else None, "classes": by_class}
    return result


def evaluate_sizes(model, dataset, classes: list[str], image_size: int, device: str) -> dict:
    """Evaluate the frozen checkpoint on the held-out image partition."""
    records = []
    for row in jsonl(dataset / "manifest.jsonl"):
        if row["split"] != "test":
            continue
        path = dataset / row["path"]
        with Image.open(path) as image:
            width, height = image.size
        targets = []
        for line in (dataset / row["annotation"]).read_text().splitlines():
            if line.strip():
                label, x, y, w, h = map(float, line.split())
                targets.append({"class_id": int(label), "box": [x - w / 2, y - h / 2, x + w / 2, y + h / 2]})
        output = model.predict(str(path), imgsz=image_size, device=device, conf=0.001, verbose=False)[0]
        predictions = [
            {"class_id": int(c), "score": float(s), "box": box}
            for box, s, c in zip(
                output.boxes.xyxyn.cpu().tolist(), output.boxes.conf.cpu().tolist(), output.boxes.cls.cpu().tolist()
            )
        ]
        records.append({"width": width, "height": height, "targets": targets, "predictions": predictions})
    return size_ap(records, classes)
