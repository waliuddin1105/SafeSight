"""Human-inspectable evidence without inferring metrics or automatic labels."""

from collections import Counter
import html
from pathlib import Path

from PIL import Image

from safesight.ingestion.video import frames
from training.common.datasets import jsonl


def failure_gallery(dataset: Path, output: Path, examples: list[dict]) -> None:
    """Save bounded thumbnails for measured false-positive/negative event examples."""
    output.mkdir(parents=True, exist_ok=True)
    cards = []
    for i, example in enumerate(examples[:24]):
        thumbnail = None
        for timestamp, rgb in frames(dataset / example["video"], 1):
            if timestamp >= example["timestamp"]:
                thumbnail = Image.fromarray(rgb)
                break
        if thumbnail is None:
            continue
        thumbnail.thumbnail((480, 320))
        name = f"failure_{i}.jpg"
        thumbnail.save(output / name)
        label = html.escape(
            f"{example['kind']}: {example['subtype']} at {example['timestamp']:.1f}s ({example['video']})"
        )
        cards.append(f'<figure><img src="{name}" alt="{label}"><figcaption>{label}</figcaption></figure>')
    (output / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>Measured failure examples</title><h1>Measured failure examples</h1><p>Review visibility and labels. Suspected label noise is a hypothesis, never a corrected label.</p>'
        + "".join(cards),
        encoding="utf-8",
    )


def dataset_inventory(root: Path, slug: str) -> dict:
    """Report per-source coverage and tiny object counts from existing annotations."""
    from safesight.contracts import YOLO_SLUGS, CLASSES

    counts, tiny, sources = Counter(), Counter(), Counter()
    for row in jsonl(root / "manifest.jsonl"):
        sources[row["group_id"]] += 1
        if slug in YOLO_SLUGS:
            with Image.open(root / row["path"]) as image:
                width, height = image.size
            for line in (root / row["annotation"]).read_text().splitlines():
                if line.strip():
                    c, _, _, w, h = map(float, line.split())
                    label = CLASSES[slug][int(c)]
                    counts[label] += 1
                    if w * width * h * height < 32**2:
                        tiny[label] += 1
    return {
        "class_instances": dict(counts),
        "objects_under_32px_area": dict(tiny),
        "groups": dict(sources),
        "label_noise": "Not inferred; inspect failure examples and validator warnings",
    }
