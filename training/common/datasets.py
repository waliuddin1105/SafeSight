"""Read-only dataset validation with provenance and leakage checks."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import av
import numpy as np
from PIL import Image
import yaml

from safesight.config import within
from safesight.contracts import CLASSES, YOLO_SLUGS

SPLITS = ("train", "val", "test")


def sha256(path: Path) -> str:
    """Stream a content digest without retaining media in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def jsonl(path: Path) -> list[dict[str, Any]]:
    """Read JSON lines, rejecting non-object records."""
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{number}: expected an object")
            records.append(record)
    return records


def valid_box(box: list[float]) -> bool:
    """Check normalized xyxy coordinates."""
    return len(box) == 4 and all(np.isfinite(box)) and 0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1


def validate_event_record(item: dict, duration: float, allowed: list[str]) -> None:
    """Require complete event timing, actor/hazard localization and visibility labels."""
    if not item.get("source_id") or not item.get("group_id") or not isinstance(item.get("events"), list):
        raise ValueError("Event video requires source_id, group_id and an events list")
    for event in item["events"]:
        if not 0 <= event["start"] < event["end"] <= duration + 0.1:
            raise ValueError("Event interval exceeds video")
        if event["subtype"] not in allowed:
            raise ValueError("Unknown event subtype")
        if not valid_box(event["box"]):
            raise ValueError("Event actor/hazard box must be normalized xyxy")
        if not isinstance(event.get("hidden_cigarette", False), bool):
            raise ValueError("hidden_cigarette must be boolean")


def video_info(path: Path) -> tuple[float, int]:
    """Decode every video frame and return duration and frame count."""
    count, end = 0, 0.0
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        fps = float(stream.average_rate or 25)
        for frame in container.decode(stream):
            count += 1
            end = max(end, float(frame.time or (count - 1) / fps) + 1 / fps)
    if count == 0:
        raise ValueError("Video contains no decodable frames")
    return end, count


@dataclass
class Validation:
    """Machine-readable validation result and evidence for quality decisions."""

    slug: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    leakage: list[dict] = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    dataset_hash: str = ""
    synthetic: bool = False

    @property
    def valid(self) -> bool:
        return not self.errors

    def write(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        payload = {**asdict(self), "valid": self.valid}
        (directory / "validation.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        lines = [
            f"# Dataset validation: {self.slug}",
            f"\nStatus: {'VALID' if self.valid else 'INVALID'}",
            f"\nDataset hash: {self.dataset_hash}",
            "\n## Errors",
        ]
        lines += [f"- {value}" for value in self.errors] or ["None."]
        lines += ["\n## Warnings"] + ([f"- {value}" for value in self.warnings] or ["None."])
        lines += ["\n## Counts", "```json", json.dumps(self.counts, indent=2), "```"]
        (directory / "validation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate(root: Path, slug: str, allow_synthetic: bool = False) -> Validation:
    """Validate a single independent dataset without creating or changing any file."""
    result = Validation(slug)
    classes = CLASSES[slug]
    manifests = root / "manifest.jsonl"
    if not manifests.is_file():
        result.errors.append(f"Missing {manifests}; follow this dataset's README")
        return result
    try:
        records = jsonl(manifests)
    except (ValueError, OSError) as error:
        result.errors.append(str(error))
        return result
    if not records:
        result.errors.append("Manifest is empty")
    result.synthetic = any(row.get("synthetic", False) for row in records)
    if result.synthetic and not allow_synthetic:
        result.errors.append("Synthetic data requires explicit --allow-synthetic / --smoke")
    counts = {split: Counter() for split in SPLITS}
    groups = {split: set() for split in SPLITS}
    samples = Counter()
    group_splits: dict[str, set] = defaultdict(set)
    sources: dict[str, set] = defaultdict(set)
    seen_ids, listed_paths = set(), set()
    content_splits: dict[str, tuple[str, str]] = {}
    signatures: list[tuple[str, str, int]] = []
    fingerprint = hashlib.sha256()
    hashed_files: set[Path] = set()

    def digest_file(path: Path) -> str:
        value = sha256(path)
        if path not in hashed_files:
            fingerprint.update(path.relative_to(root).as_posix().encode())
            fingerprint.update(value.encode())
            hashed_files.add(path)
        return value

    digest_file(manifests)
    if slug in YOLO_SLUGS:
        try:
            data = yaml.safe_load((root / "data.yaml").read_text(encoding="utf-8"))
            names = data["names"]
            if isinstance(names, dict):
                names = [names[i] for i in range(len(names))]
            if names != classes:
                raise ValueError(f"data.yaml names must be {classes}")
            for split in SPLITS:
                if data[split] != f"images/{split}":
                    raise ValueError(f"data.yaml {split} must be images/{split}")
            if data.get("download"):
                raise ValueError("Dataset download instructions are forbidden")
            digest_file(root / "data.yaml")
        except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as error:
            result.errors.append(f"Invalid data.yaml: {error}")

    for index, record in enumerate(records):
        try:
            for key in ("sample_id", "path", "annotation", "source_id", "group_id", "split", "start", "end"):
                if key not in record:
                    raise ValueError(f"Missing manifest field {key}")
            split = record["split"]
            if split not in SPLITS or not record["group_id"] or not record["source_id"]:
                raise ValueError("Invalid split/source/group")
            if not all(np.isfinite([record["start"], record["end"]])) or not 0 <= record["start"] <= record["end"]:
                raise ValueError("Invalid source time interval")
            if record["sample_id"] in seen_ids or record["path"] in listed_paths:
                raise ValueError("Duplicate sample ID or path")
            seen_ids.add(record["sample_id"])
            listed_paths.add(record["path"])
            expected = "clips" if slug == "entrance_guard" else "images"
            if not record["path"].startswith(f"{expected}/{split}/"):
                raise ValueError("Media path does not match its split")
            media = within(root, record["path"])
            annotation = within(root, record["annotation"])
            if not media.is_file() or media.stat().st_size == 0:
                raise ValueError("Missing or empty media")
            if not annotation.is_file():
                raise ValueError("Missing annotation; negative YOLO samples need an explicit empty label")
            signature = digest_file(media)
            digest_file(annotation)
            previous = content_splits.get(signature)
            if previous and previous[0] != split:
                result.errors.append(f"Exact duplicate across splits: {previous[1]} / {record['path']}")
            content_splits[signature] = (split, record["path"])
            group_splits[record["group_id"]].add(split)
            sources[record["source_id"]].add(split)
            groups[split].add(record["group_id"])
            samples[split] += 1
            if slug == "entrance_guard":
                duration, _ = video_info(media)
                ann = json.loads(annotation.read_text(encoding="utf-8"))
                label = ann["label"]
                if label not in classes:
                    raise ValueError("Unknown entrance class")
                counts[split][label] += 1
                phases = ann.get("phases", [])
                for phase in phases:
                    if (
                        phase["name"] not in ("stop", "frisk", "bag_inspection", "permission", "crossing")
                        or not 0 <= phase["start"] < phase["end"] <= duration + 0.1
                    ):
                        raise ValueError("Invalid entrance phase interval")
                if label in ("verified_entry", "unverified_entry") and not 0 <= ann["crossing_time"] <= duration:
                    raise ValueError("Completed entry needs a valid crossing timestamp")
                if label == "verified_entry":
                    required = (
                        ["stop", "frisk"]
                        + (["bag_inspection"] if ann["bag_present"] else [])
                        + ["permission", "crossing"]
                    )
                    names = [p["name"] for p in phases]
                    if (
                        names != required
                        or any(a["end"] > b["start"] for a, b in zip(phases, phases[1:]))
                        or not ann.get("fully_visible")
                    ):
                        raise ValueError("Verified entry requires visible ordered mandatory phases")
            else:
                with Image.open(media) as image:
                    image.load()
                    if min(image.size) < 8:
                        raise ValueError("Image dimensions are too small")
                    small = np.asarray(image.convert("L").resize((9, 8)))
                    bits = (small[:, 1:] > small[:, :-1]).flatten()
                    perceptual = sum(int(bit) << n for n, bit in enumerate(bits))
                    signatures.append((split, record["path"], perceptual))
                if slug in YOLO_SLUGS:
                    if annotation.stem != media.stem or annotation.suffix != ".txt":
                        raise ValueError("YOLO annotation stem/extension does not match image")
                    lines = annotation.read_text(encoding="utf-8").splitlines()
                    for line in lines:
                        if not line.strip():
                            continue
                        parts = line.split()
                        if len(parts) != 5:
                            raise ValueError("YOLO label requires five fields")
                        class_id = int(parts[0])
                        x, y, w, h = map(float, parts[1:])
                        if not 0 <= class_id < len(classes) or not valid_box(
                            [x - w / 2, y - h / 2, x + w / 2, y + h / 2]
                        ):
                            raise ValueError("Invalid class or normalized YOLO box")
                        counts[split][classes[class_id]] += 1
                    if not any(line.strip() for line in lines):
                        counts[split]["negative_images"] += 1
                else:
                    ann = json.loads(annotation.read_text(encoding="utf-8"))
                    for person in ann["people"]:
                        if person["label"] not in classes or not valid_box(person["box"]):
                            raise ValueError("Invalid body label or person box")
                        if "landmarks" in person:
                            array = np.asarray(person["landmarks"])
                            if not record.get("synthetic") or array.shape != (33, 4) or not np.isfinite(array).all():
                                raise ValueError("Inline landmarks are reserved for valid synthetic fixtures")
                        counts[split][person["label"]] += 1
        except (OSError, ValueError, KeyError, TypeError, IndexError, av.error.FFmpegError) as error:
            result.errors.append(f"Manifest row {index + 1}: {error}")

    for kind, mapping in (("group", group_splits), ("source", sources)):
        for identifier, partitions in mapping.items():
            if len(partitions) > 1:
                result.errors.append(f"{kind} {identifier} leaks across {sorted(partitions)}")
    # Four 16-bit buckets retrieve every pair with Hamming distance <=3.
    buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
    for index, (split, path, signature) in enumerate(signatures):
        candidates = set()
        for shift in range(4):
            candidates.update(buckets[(shift, (signature >> (shift * 16)) & 65535)])
        for other in candidates:
            other_split, other_path, other_signature = signatures[other]
            if split != other_split and (signature ^ other_signature).bit_count() <= 3:
                result.leakage.append({"kind": "suspected_near_duplicate", "paths": [other_path, path]})
        for shift in range(4):
            buckets[(shift, (signature >> (shift * 16)) & 65535)].append(index)
    if result.leakage:
        result.warnings.append(
            f"Review {len(result.leakage)} suspected cross-split near-duplicates; production gate cannot pass"
        )

    if slug != "entrance_guard":
        for split in ("val", "test"):
            try:
                event_path = root / "events" / f"{split}.jsonl"
                evaluation = jsonl(event_path)
                digest_file(event_path)
                if not evaluation:
                    raise ValueError("Event evaluation list is empty")
                for item in evaluation:
                    video = within(root, item["video"])
                    if not item["video"].startswith(f"videos/{split}/"):
                        raise ValueError("Event video is outside its split")
                    duration, _ = video_info(video)
                    content_hash = digest_file(video)
                    previous = content_splits.get(content_hash)
                    if previous and previous[0] != split:
                        raise ValueError(f"Evaluation video is duplicated across splits: {previous[1]}")
                    content_splits[content_hash] = (split, item["video"])
                    validate_event_record(item, duration, alert_classes(slug))
                    if item["group_id"] in group_splits and group_splits[item["group_id"]] != {split}:
                        raise ValueError("Evaluation group overlaps another split")
                    if item["source_id"] in sources and sources[item["source_id"]] != {split}:
                        raise ValueError("Evaluation source overlaps another split")
                    group_splits[item["group_id"]].add(split)
                    sources[item["source_id"]].add(split)
                    for event in item["events"]:
                        if not 0 <= event["start"] < event["end"] <= duration + 0.1:
                            raise ValueError("Event interval exceeds video")
                        if event["subtype"] not in alert_classes(slug):
                            raise ValueError("Unknown event subtype")
            except (OSError, ValueError, KeyError, IndexError, TypeError, av.error.FFmpegError) as error:
                result.errors.append(f"{split} event annotations: {error}")
    for split in SPLITS:
        for label in classes:
            if counts[split][label] == 0:
                result.errors.append(f"{split}: missing class {label}")
        values = [counts[split][label] for label in classes]
        if min(values, default=0) and max(values) / min(values) > 5:
            result.warnings.append(f"{split}: class imbalance exceeds 5:1")
        if len(groups[split]) < (20 if split == "train" else 5):
            result.warnings.append(f"{split}: too few independent groups ({len(groups[split])})")
    total = sum(samples.values())
    if total:
        for split, target in zip(SPLITS, (0.7, 0.15, 0.15)):
            if abs(samples[split] / total - target) > 0.12:
                result.warnings.append(
                    f"{split}: sample fraction {samples[split] / total:.2f} differs from recommended {target}"
                )
    expected_folder = "clips" if slug == "entrance_guard" else "images"
    actual = {p.relative_to(root).as_posix() for p in (root / expected_folder).rglob("*") if p.is_file()}
    if actual - listed_paths:
        result.errors.append(f"{len(actual - listed_paths)} media files are missing from manifest")
    result.counts = {
        split: {"samples": samples[split], "groups": len(groups[split]), "classes": dict(counts[split])}
        for split in SPLITS
    }
    result.dataset_hash = fingerprint.hexdigest()
    return result


def alert_classes(slug: str) -> list[str]:
    """Return alert categories separately from detector classes."""
    return {
        "body_state": ["deep_bend", "lying_on_floor"],
        "phone_usage": ["phone_usage"],
        "cigarette_smoking": ["smoking"],
        "entrance_guard": ["unverified_entry"],
        "fire_smoke": ["fire", "hazardous_smoke", "uncertain_smoke"],
    }[slug]


def audit_cross_dataset(roots: dict[str, Path]) -> list[str]:
    """Find source/group identities assigned to different splits across tasks."""
    seen: dict[tuple[str, str], tuple[str, str]] = {}
    errors = []
    for slug, root in roots.items():
        if not (root / "manifest.jsonl").exists():
            continue
        records = jsonl(root / "manifest.jsonl")
        for split in ("val", "test"):
            path = root / "events" / f"{split}.jsonl"
            if path.exists():
                records += [{**r, "split": split} for r in jsonl(path)]
        for row in records:
            for identity_field in ("source_id", "group_id"):
                key = (identity_field, row[identity_field])
                if key in seen and seen[key][1] != row["split"]:
                    errors.append(
                        f"{identity_field} {row[identity_field]}: {seen[key]} conflicts with {(slug, row['split'])}"
                    )
                seen[key] = (slug, row["split"])
    return errors
