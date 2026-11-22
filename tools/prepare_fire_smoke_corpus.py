"""Acquire and combine pinned D-Fire and FireViewer/FASDD detector sources."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tarfile
import time
from typing import Any, Iterable

from PIL import Image
import polars as pl
import requests
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from safesight.config import ROOT, within


SOURCES = {
    "dfire_train": {
        "url": "https://huggingface.co/datasets/hanvithSai/gavin-dfire-raw/resolve/main/train.tar?download=true",
        "path": "dfire/train.tar",
        "bytes": 2_598_529_536,
        "sha256": "48d8586d1fa4444d1bb97a693ed6f023155ef7d5aa26fa545bedac10c90633c9",
        "license": "CC-BY-4.0 mirror attribution; upstream provider terms also apply",
    },
    "dfire_test": {
        "url": "https://huggingface.co/datasets/hanvithSai/gavin-dfire-raw/resolve/main/test.tar?download=true",
        "path": "dfire/test.tar",
        "bytes": 639_836_160,
        "sha256": "593cb2d08cf8ec1176eaad6d0f682ce2eaf7cc9513beacf58823a9ba16429d30",
        "license": "CC-BY-4.0 mirror attribution; upstream provider terms also apply",
    },
    "fireviewer_train_00000": {
        "url": "https://huggingface.co/datasets/fireviewer/fire-smoke-detection-corpus-v1/resolve/main/data/train/train-00000.parquet?download=true",
        "path": "fireviewer/train-00000.parquet",
        "bytes": 1_094_714_189,
        "sha256": "1b990c22941089cff808fb4d694372fbfb7e930fb953921d9db801c04f0c332a",
        "license": "Per-row rights metadata; selected rows are CC-BY-SA-4.0",
    },
    "fireviewer_train_00001": {
        "url": "https://huggingface.co/datasets/fireviewer/fire-smoke-detection-corpus-v1/resolve/main/data/train/train-00001.parquet?download=true",
        "path": "fireviewer/train-00001.parquet",
        "bytes": 463_780_358,
        "sha256": "3d4d39f287729fac19d3ab830cb44b2d34d545182747076da14edb0cb1c25524",
        "license": "Per-row rights metadata; selected rows are CC-BY-SA-4.0",
    },
}

CLASS_IDS = {"smoke_visible": 0, "flame_visible": 1}
CHUNK_BYTES = 4 * 1024 * 1024


def sha256(path: Path) -> str:
    """Hash a source or generated file without loading it all into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(source: dict[str, Any], destination: Path, attempts: int = 30) -> None:
    """Resume a pinned public source, retrying transient connection failures."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    expected_size = int(source["bytes"])
    if destination.is_file() and destination.stat().st_size == expected_size:
        if sha256(destination) != source["sha256"]:
            raise ValueError(f"Cached source checksum mismatch: {destination}")
        return
    for attempt in range(1, attempts + 1):
        offset = destination.stat().st_size if destination.exists() else 0
        if offset > expected_size:
            raise ValueError(f"Cached source is larger than expected: {destination}")
        headers = {"User-Agent": "SafeSight/1.0"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        try:
            with requests.get(source["url"], stream=True, timeout=(30, 180), headers=headers) as response:
                response.raise_for_status()
                if offset and response.status_code != 206:
                    raise ValueError("Source rejected a validated byte-range resume")
                mode = "ab" if offset else "wb"
                with destination.open(mode) as target:
                    for chunk in response.iter_content(CHUNK_BYTES):
                        if chunk:
                            target.write(chunk)
                            target.flush()
        except requests.RequestException as error:
            if attempt == attempts:
                raise RuntimeError(f"Download failed after {attempts} attempts: {destination.name}") from error
            time.sleep(min(30, attempt * 3))
            continue
        if destination.stat().st_size == expected_size:
            break
    if destination.stat().st_size != expected_size or sha256(destination) != source["sha256"]:
        raise ValueError(f"Incomplete or corrupt pinned source: {destination}")


def safe_name(value: str) -> str:
    """Create a portable collision-safe stem from publisher identifiers."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-")
    if not cleaned:
        raise ValueError("Publisher sample identifier cannot produce a portable filename")
    return cleaned[:160]


def write_immutable(path: Path, content: bytes) -> None:
    """Create or verify a generated corpus file without overwriting differences."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(content).digest():
            raise ValueError(f"Existing generated file differs; preserving it: {path}")
        return
    temporary = path.with_suffix(path.suffix + ".safesight-part")
    temporary.write_bytes(content)
    temporary.replace(path)


def yolo_lines(annotations: Iterable[dict[str, Any]], width: int, height: int) -> bytes:
    """Convert strict FireViewer pixel xywh boxes to SafeSight normalized YOLO labels."""
    lines = []
    for annotation in annotations:
        name = annotation.get("class_name")
        if name not in CLASS_IDS or int(annotation.get("class_id", -1)) != CLASS_IDS[name]:
            raise ValueError(f"Unexpected FireViewer class contract: {annotation}")
        x, y, box_width, box_height = map(float, annotation["bbox_xywh"])
        if width <= 0 or height <= 0 or box_width <= 0 or box_height <= 0:
            raise ValueError("Invalid FireViewer image or box dimensions")
        x1, y1 = max(0.0, x), max(0.0, y)
        x2, y2 = min(float(width), x + box_width), min(float(height), y + box_height)
        if x2 <= x1 or y2 <= y1:
            raise ValueError("FireViewer box lies outside its image")
        lines.append(
            f"{CLASS_IDS[name]} {(x1 + x2) / (2 * width):.8f} {(y1 + y2) / (2 * height):.8f} "
            f"{(x2 - x1) / width:.8f} {(y2 - y1) / height:.8f}"
        )
    return (("\n".join(lines) + "\n") if lines else "").encode()


def repair_dfire_labels(content: bytes) -> tuple[bytes, list[str], int, int]:
    """Drop zero-area points and clip publisher boxes that extend beyond the image."""
    classes: list[str] = []
    repaired: list[str] = []
    dropped = clipped = 0
    changed = False
    for line in content.decode().splitlines():
        fields = line.split()
        if len(fields) != 5 or fields[0] not in ("0", "1"):
            raise ValueError("Invalid D-Fire YOLO label shape or class")
        values = [float(value) for value in fields[1:]]
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Non-finite D-Fire YOLO coordinate")
        center_x, center_y, width, height = values
        x1, y1 = max(0.0, center_x - width / 2), max(0.0, center_y - height / 2)
        x2, y2 = min(1.0, center_x + width / 2), min(1.0, center_y + height / 2)
        if width <= 0 or height <= 0 or x2 <= x1 or y2 <= y1:
            dropped += 1
            changed = True
            continue
        normalized = (
            (x1 + x2) / 2,
            (y1 + y2) / 2,
            x2 - x1,
            y2 - y1,
        )
        if any(value < 0 or value > 1 for value in values) or any(
            abs(original - fixed) > 1e-10 for original, fixed in zip(values, normalized)
        ):
            clipped += 1
            changed = True
        repaired.append(f"{fields[0]} " + " ".join(f"{value:.8f}" for value in normalized))
        classes.append(fields[0])
    if content.strip() and not classes:
        raise ValueError("D-Fire positive label contains no valid boxes after repair")
    output = (("\n".join(repaired) + "\n").encode() if changed else content)
    return output, classes, dropped, clipped


def register_sample(
    root: Path,
    records: list[dict[str, Any]],
    seen: dict[str, bytes],
    *,
    stem: str,
    image_bytes: bytes,
    label_bytes: bytes,
    suffix: str,
    source_id: str,
    group_id: str,
    publisher: str,
    license_name: str,
    publisher_sample_id: str,
    publisher_label_bytes: bytes | None = None,
) -> bool:
    """Publish one exact-deduplicated sample and append its provenance record."""
    image_hash = hashlib.sha256(image_bytes).hexdigest()
    if image_hash in seen:
        return False  # Prefer the first strict-validated source, including label disagreements.
    seen[image_hash] = label_bytes
    safe_stem = safe_name(stem) + "-" + image_hash[:12]
    image_path = f"images/{publisher}/{safe_stem}{suffix}"
    label_path = f"labels/{publisher}/{safe_stem}.txt"
    write_immutable(within(root, image_path), image_bytes)
    label_target = within(root, label_path)
    if (
        label_target.is_file()
        and label_target.read_bytes() != label_bytes
        and publisher_label_bytes is not None
        and label_target.read_bytes() == publisher_label_bytes
    ):
        # Reconcile an interrupted pre-repair import only when the existing file is
        # byte-for-byte identical to the verified publisher annotation.
        label_target.write_bytes(label_bytes)
    else:
        write_immutable(label_target, label_bytes)
    records.append(
        {
            "sample_id": f"{publisher}-{safe_stem}",
            "path": image_path,
            "annotation": label_path,
            "source_id": source_id,
            "group_id": group_id,
            "start": 0.0,
            "end": 0.0,
            "publisher": publisher,
            "license": license_name,
            "publisher_sample_id": publisher_sample_id,
        }
    )
    return True


def import_fireviewer(
    shards: Iterable[Path], root: Path, records: list[dict[str, Any]], seen: dict[str, bytes]
) -> Counter:
    """Import strict-validated FASDD rows from FireViewer parquet shards."""
    counts: Counter = Counter()
    columns = [
        "image",
        "sample_id",
        "split_group",
        "width",
        "height",
        "license",
        "sample_validation_status",
        "annotations_json",
    ]
    for shard in shards:
        frame = pl.read_parquet(shard, columns=columns, low_memory=True)
        for row in frame.iter_rows(named=True):
            counts["source_images"] += 1
            if row["sample_validation_status"] != "strict_automated_validated":
                raise ValueError("FireViewer row is not strict-validated")
            if row["license"] != "CC-BY-SA-4.0":
                raise ValueError(f"Unexpected FireViewer row license: {row['license']}")
            group = row["split_group"]
            if not isinstance(group, str) or not group:
                raise ValueError("FireViewer row lacks a source-aware split group")
            image = row["image"]
            image_bytes = image.get("bytes") if isinstance(image, dict) else None
            if not image_bytes:
                raise ValueError("FireViewer row lacks embedded image bytes")
            with Image.open(io.BytesIO(image_bytes)) as opened:
                opened.verify()
                suffix = ".png" if opened.format == "PNG" else ".jpg"
            annotations = json.loads(row["annotations_json"])
            label_bytes = yolo_lines(annotations, int(row["width"]), int(row["height"]))
            if register_sample(
                root,
                records,
                seen,
                stem=row["sample_id"],
                image_bytes=image_bytes,
                label_bytes=label_bytes,
                suffix=suffix,
                source_id=f"fireviewer:{group}",
                group_id=f"fireviewer:{group}",
                publisher="fireviewer",
                license_name=row["license"],
                publisher_sample_id=row["sample_id"],
            ):
                counts["images"] += 1
                if not annotations:
                    counts["negative_images"] += 1
                for annotation in annotations:
                    counts[annotation["class_name"]] += 1
        del frame
    return counts


def _member_bytes(archive: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    source = archive.extractfile(member)
    if source is None:
        raise ValueError(f"Unreadable tar member: {member.name}")
    with source:
        return source.read()


def import_dfire(
    archives: Iterable[Path], root: Path, records: list[dict[str, Any]], seen: dict[str, bytes]
) -> Counter:
    """Import D-Fire tar members, conservatively grouping its source families."""
    counts: Counter = Counter()
    for path in archives:
        with tarfile.open(path, "r") as archive:
            members = [
                member
                for member in archive.getmembers()
                if member.isfile()
                and not any(part.startswith("._") or part == ".DS_Store" for part in PurePosixPath(member.name).parts)
            ]
            labels = {
                PurePosixPath(member.name).stem: _member_bytes(archive, member)
                for member in members
                if PurePosixPath(member.name).suffix.lower() == ".txt"
            }
            for member in members:
                member_path = PurePosixPath(member.name)
                if member_path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
                    continue
                counts["source_images"] += 1
                stem = member_path.stem
                if stem not in labels:
                    raise ValueError(f"D-Fire image lacks an explicit label file: {stem}")
                try:
                    label_bytes, parsed, dropped, clipped = repair_dfire_labels(labels[stem])
                except ValueError as error:
                    raise ValueError(f"Invalid D-Fire label for {stem}: {error}") from error
                prefix_match = re.match(r"[A-Za-z]+", stem)
                family = (prefix_match.group(0) if prefix_match else "other").lower()
                if family not in ("aof", "web", "publicdataset"):
                    family = "other"
                image_bytes = _member_bytes(archive, member)
                with Image.open(io.BytesIO(image_bytes)) as opened:
                    opened.verify()
                if register_sample(
                    root,
                    records,
                    seen,
                    stem=stem,
                    image_bytes=image_bytes,
                    label_bytes=label_bytes,
                    suffix=member_path.suffix.lower(),
                    source_id=f"dfire:{family}",
                    group_id=f"dfire:{family}",
                    publisher="dfire",
                    license_name="CC-BY-4.0 mirror attribution; upstream provider terms also apply",
                    publisher_sample_id=stem,
                    publisher_label_bytes=labels[stem],
                ):
                    counts["images"] += 1
                    counts["invalid_boxes_dropped"] += dropped
                    counts["out_of_bounds_boxes_clipped"] += clipped
                    if not parsed:
                        counts["negative_images"] += 1
                    for class_id in parsed:
                        counts["smoke_visible" if class_id == "0" else "flame_visible"] += 1
    return counts


def prepare(dataset_root: Path, cache_root: Path) -> dict[str, Any]:
    """Download, verify and publish the combined unsplit detector corpus."""
    dataset_root = dataset_root.resolve()
    cache_root = cache_root.resolve()
    receipt = dataset_root / "preparation.json"
    source_fingerprint = hashlib.sha256(
        json.dumps({name: source["sha256"] for name, source in SOURCES.items()}, sort_keys=True).encode()
    ).hexdigest()
    if receipt.is_file():
        existing = json.loads(receipt.read_text(encoding="utf-8"))
        if existing.get("source_fingerprint") == source_fingerprint and (dataset_root / "manifest.jsonl").is_file():
            return existing
        raise ValueError("Existing fire/smoke preparation differs; preserve it and use a new dataset root")
    cache_root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(cache_root).free < 25 * 1024**3:
        raise ValueError("At least 25 GiB free is required for downloads, generated corpus and split staging")
    paths = {}
    for name, source in SOURCES.items():
        path = within(cache_root, source["path"])
        download(source, path)
        paths[name] = path
    records: list[dict[str, Any]] = []
    seen: dict[str, bytes] = {}
    fireviewer = import_fireviewer(
        [paths["fireviewer_train_00000"], paths["fireviewer_train_00001"]], dataset_root, records, seen
    )
    dfire = import_dfire([paths["dfire_train"], paths["dfire_test"]], dataset_root, records, seen)
    records.sort(key=lambda row: row["sample_id"])
    manifest = "".join(json.dumps(row, sort_keys=True) + "\n" for row in records).encode()
    write_immutable(
        dataset_root / "data.yaml",
        yaml.safe_dump({"path": ".", "train": "images/train", "val": "images/val", "test": "images/test", "names": ["smoke", "fire"]}).encode(),
    )
    write_immutable(dataset_root / "manifest.jsonl", manifest)
    write_immutable(
        dataset_root / "ATTRIBUTION.md",
        (
            "# Combined fire/smoke detector corpus\n\n"
            "This local corpus contains pinned D-Fire (CC BY 4.0 mirror attribution; upstream provider terms "
            "also apply) and strict-validated FASDD rows from FireViewer (CC BY-SA 4.0). Retain citations "
            "and the immutable hashes in `preparation.json`.\n"
        ).encode(),
    )
    result = {
        "schema_version": 1,
        "source_fingerprint": source_fingerprint,
        "sources": {
            name: {key: value for key, value in source.items() if key != "url"} for name, source in SOURCES.items()
        },
        "records": len(records),
        "exact_duplicates_skipped": fireviewer["source_images"] + dfire["source_images"] - len(records),
        "fireviewer": dict(fireviewer),
        "dfire": dict(dfire),
        "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
    }
    write_immutable(receipt, (json.dumps(result, indent=2, sort_keys=True) + "\n").encode())
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, default=ROOT / "datasets/fire_smoke")
    parser.add_argument("--cache-root", type=Path, default=ROOT / "datasets/_downloads/fire_smoke")
    args = parser.parse_args()
    print(json.dumps(prepare(args.dataset_root, args.cache_root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
