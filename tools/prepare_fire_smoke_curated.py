"""Acquire, normalize, audit, and assemble the curated fire/smoke image corpus.

This command never trains a model. Suspicious samples are quarantined rather than
silently repaired, and unreviewed target-footage predictions never enter training.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import random
import re
import shutil
import sys
import tempfile
import time
from typing import Any, Iterable
import zipfile

import av
from dotenv import load_dotenv
from PIL import Image, ImageChops, ImageDraw, ImageStat
import requests
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from safesight.config import ROOT, read_yaml, resolve_path, within


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
CHUNK = 4 * 1024 * 1024


@dataclass(frozen=True)
class Box:
    class_id: int
    x: float
    y: float
    width: float
    height: float

    @property
    def area(self) -> float:
        return self.width * self.height

    def line(self) -> str:
        return f"{self.class_id} {self.x:.8f} {self.y:.8f} {self.width:.8f} {self.height:.8f}"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            value.update(block)
    return value.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".safesight-part")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def dhash(image: Image.Image) -> int:
    small = image.convert("L").resize((9, 8))
    pixels = list(small.getdata())
    return sum(
        int(pixels[row * 9 + column + 1] > pixels[row * 9 + column]) << (row * 8 + column)
        for row in range(8)
        for column in range(8)
    )


def visually_near(first: Path, second: Path, maximum_mean_difference: float = 12.0) -> bool:
    """Confirm a hash candidate using color-pixel distance to reduce false matches."""
    with Image.open(first) as first_image, Image.open(second) as second_image:
        left = first_image.convert("RGB").resize((64, 64))
        right = second_image.convert("RGB").resize((64, 64))
        return max(ImageStat.Stat(ImageChops.difference(left, right)).mean) <= maximum_mean_difference


def safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        for member in source.infolist():
            relative = PurePosixPath(member.filename)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"Unsafe archive member: {member.filename}")
            target = (destination / Path(*relative.parts)).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise ValueError(f"Archive member escapes extraction root: {member.filename}")
        source.extractall(destination)


def names_from_yaml(root: Path) -> list[str]:
    candidates = list(root.rglob("data.yaml"))
    if not candidates:
        raise ValueError("Roboflow export has no data.yaml")
    data = yaml.safe_load(candidates[0].read_text(encoding="utf-8"))
    names = data.get("names") if isinstance(data, dict) else None
    if isinstance(names, dict):
        names = [name for _, name in sorted(((int(key), value) for key, value in names.items()))]
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
        raise ValueError("Dataset class names are missing or invalid")
    return names


def normalize_name(value: str) -> str:
    return value.casefold().strip().replace("_", " ").replace("-", " ")


def scene_group(source: str, stem: str) -> str:
    """Keep exported variants and apparent video-frame sequences in one split group."""
    value = stem.split(".rf.", 1)[0]
    value = re.sub(r"_(?:jpg|jpeg|png)$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"(?:[-_](?:frame)?\d{3,})$", "", value, flags=re.IGNORECASE)
    return f"{source}:{value or stem}"


def parse_labels(path: Path, names: list[str], aliases: dict[str, str]) -> tuple[list[Box], int]:
    boxes: list[Box] = []
    ignored = 0
    alias_map = {normalize_name(key): value for key, value in aliases.items()}
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 5:
            raise ValueError(f"line {number} does not contain five YOLO fields")
        source_id = int(fields[0])
        if not 0 <= source_id < len(names):
            raise ValueError(f"line {number} has unknown class id {source_id}")
        mapped = alias_map.get(normalize_name(names[source_id]))
        if mapped is None:
            raise ValueError(f"unmapped class name {names[source_id]!r}")
        if mapped == "other":
            ignored += 1
            continue
        if mapped not in ("smoke", "fire"):
            raise ValueError(f"invalid mapped class {mapped!r}")
        values = [float(value) for value in fields[1:]]
        if any(not 0 <= value <= 1 for value in values) or values[2] <= 0 or values[3] <= 0:
            raise ValueError(f"line {number} has invalid normalized coordinates")
        x, y, width, height = values
        if x - width / 2 < -1e-7 or y - height / 2 < -1e-7 or x + width / 2 > 1.0000001 or y + height / 2 > 1.0000001:
            raise ValueError(f"line {number} extends outside the image")
        boxes.append(Box(0 if mapped == "smoke" else 1, x, y, width, height))
    return boxes, ignored


def label_for(image: Path) -> Path | None:
    parts = list(image.parts)
    try:
        index = max(position for position, part in enumerate(parts) if part == "images")
    except ValueError:
        return None
    parts[index] = "labels"
    return Path(*parts).with_suffix(".txt")


def iter_export_images(root: Path) -> Iterable[Path]:
    for image in root.rglob("*"):
        if image.is_file() and image.suffix.casefold() in IMAGE_SUFFIXES and "images" in image.parts:
            yield image


def iou(first: Box, second: Box) -> float:
    ax1, ay1, ax2, ay2 = first.x-first.width/2, first.y-first.height/2, first.x+first.width/2, first.y+first.height/2
    bx1, by1, bx2, by2 = second.x-second.width/2, second.y-second.height/2, second.x+second.width/2, second.y+second.height/2
    intersection = max(0.0, min(ax2, bx2)-max(ax1, bx1)) * max(0.0, min(ay2, by2)-max(ay1, by1))
    return intersection / max(first.area + second.area - intersection, 1e-12)


def audit_boxes(boxes: list[Box]) -> list[str]:
    reasons: list[str] = []
    if any(box.class_id == 0 and box.area > 0.8 for box in boxes):
        reasons.append("smoke_box_area_over_0.8")
    for index, first in enumerate(boxes):
        for second in boxes[index + 1:]:
            if first.class_id == second.class_id and iou(first, second) > 0.95:
                reasons.append("near_duplicate_same_class_boxes")
                return reasons
    return reasons


def roboflow_export_endpoint(source: dict[str, Any]) -> str:
    """Return the official SDK-compatible export endpoint without credentials."""
    return (
        f"https://api.roboflow.com/{source['workspace']}/{source['project']}/"
        f"{source['version']}/yolov8"
    )


def roboflow_export(source: dict[str, Any], key: str) -> tuple[str, dict[str, Any]]:
    endpoint = roboflow_export_endpoint(source)
    deadline = time.monotonic() + 30 * 60
    while True:
        try:
            response = requests.get(endpoint, params={"api_key": key}, timeout=60)
            response.raise_for_status()
        except requests.RequestException as error:
            status = error.response.status_code if error.response is not None else "network-error"
            raise RuntimeError(
                f"Roboflow export request failed ({status}) for {source['project']} v{source['version']}"
            ) from None
        if response.status_code != 202:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Roboflow export timed out for {source['project']} v{source['version']}")
        time.sleep(5)
    if "zip" in response.headers.get("content-type", ""):
        return response.url, {"endpoint": endpoint}
    payload = response.json()
    link = payload.get("export", {}).get("link") or payload.get("link")
    if not isinstance(link, str) or not link.startswith("https://"):
        raise ValueError(f"Roboflow did not provide an export link for {source['project']} v{source['version']}")
    return link, {"endpoint": endpoint, "export": {key: value for key, value in payload.get("export", {}).items() if key != "link"}}


def download_segment(url: str, destination: Path, start: int, end: int, attempts: int = 5) -> int:
    """Download one validated byte range without exposing its signed URL in errors."""
    expected = end - start + 1
    temporary = destination.with_suffix(destination.suffix + ".part")
    for attempt in range(1, attempts + 1):
        try:
            with requests.get(
                url,
                headers={"Range": f"bytes={start}-{end}", "User-Agent": "SafeSight/1.0"},
                stream=True,
                timeout=(30, 180),
            ) as response:
                if response.status_code != 206:
                    raise RuntimeError(f"range response was {response.status_code}")
                with temporary.open("wb") as handle:
                    for block in response.iter_content(1024 * 1024):
                        if block:
                            handle.write(block)
            if temporary.stat().st_size != expected:
                raise RuntimeError("range length mismatch")
            temporary.replace(destination)
            return expected
        except (OSError, requests.RequestException, RuntimeError):
            temporary.unlink(missing_ok=True)
            if attempt == attempts:
                raise RuntimeError(f"Segment download failed after {attempts} attempts: {start}-{end}") from None
            time.sleep(attempt * 2)
    raise AssertionError("unreachable")


def download_file(url: str, destination: Path, workers: int = 48, segment_bytes: int = 2 * 1024 * 1024) -> None:
    """Resume a signed download using validated parallel ranges."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        head = requests.head(url, timeout=60, allow_redirects=True)
        head.raise_for_status()
        total = int(head.headers["content-length"])
        if head.headers.get("accept-ranges", "").casefold() != "bytes":
            raise RuntimeError("provider does not support byte ranges")
    except (KeyError, ValueError, requests.RequestException, RuntimeError):
        raise RuntimeError("Unable to inspect the signed dataset archive") from None
    parts = destination.with_suffix(destination.suffix + ".parts")
    parts.mkdir(parents=True, exist_ok=True)
    ranges = [(start, min(total - 1, start + segment_bytes - 1)) for start in range(0, total, segment_bytes)]
    completed = 0
    pending: list[tuple[int, int, Path]] = []
    for index, (start, end) in enumerate(ranges):
        part = parts / f"{index:06d}.part"
        expected = end - start + 1
        if part.is_file() and part.stat().st_size == expected:
            completed += expected
        else:
            part.unlink(missing_ok=True)
            pending.append((start, end, part))
    print(f"  Resuming {destination.name}: {completed / 1024**2:.1f}/{total / 1024**2:.1f} MiB", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(download_segment, url, part, start, end): (start, end) for start, end, part in pending}
        for future in as_completed(futures):
            completed += future.result()
            print(f"  {destination.name}: {100 * completed / total:.1f}%", flush=True)
    assembled = destination.with_suffix(destination.suffix + ".assembling")
    with assembled.open("wb") as output:
        for index in range(len(ranges)):
            with (parts / f"{index:06d}.part").open("rb") as source:
                shutil.copyfileobj(source, output, CHUNK)
    if assembled.stat().st_size != total:
        raise RuntimeError(f"Assembled archive has the wrong size: {destination.name}")
    assembled.replace(destination)
    shutil.rmtree(parts)
    try:
        destination.with_suffix(destination.suffix + ".part").unlink(missing_ok=True)
    except PermissionError:
        # A superseded downloader may still hold the legacy file on Windows.
        # The assembled, size-verified archive is already complete.
        pass


def acquire(config: dict[str, Any], selected: set[str] | None = None) -> dict[str, Any]:
    load_dotenv(ROOT / ".env")
    key = os.getenv("ROBOFLOW_API_KEY", "").strip()
    if not key:
        raise RuntimeError("ROBOFLOW_API_KEY is empty; set it in the ignored .env file")
    cache = resolve_path(config["cache"])
    report: dict[str, Any] = {}
    for name, source in sorted(config["sources"].items(), key=lambda item: item[1]["priority"]):
        if selected and name not in selected:
            continue
        archive = cache / f"{name}-v{source['version']}.zip"
        receipt = archive.with_suffix(".receipt.json")
        if not archive.exists():
            link, metadata = roboflow_export(source, key)
            download_file(link, archive)
        row = {
            "project": source["project"], "version": source["version"], "url": source["url"],
            "license": source["license"], "archive": str(archive.relative_to(ROOT)),
            "sha256": digest(archive), "bytes": archive.stat().st_size,
        }
        write_json(receipt, row)
        report[name] = row
    return report


def copy_sample(image: Path, boxes: list[Box], source_name: str, sample_id: str, output: Path) -> tuple[str, str]:
    image_hash = digest(image)
    stem = f"{source_name}-{sample_id[:100]}-{image_hash[:12]}"
    image_relative = Path("images") / source_name / f"{stem}{image.suffix.casefold()}"
    label_relative = Path("labels") / source_name / f"{stem}.txt"
    image_target, label_target = output / image_relative, output / label_relative
    image_target.parent.mkdir(parents=True, exist_ok=True)
    label_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(image, image_target)
    label_target.write_text(("\n".join(box.line() for box in boxes) + "\n") if boxes else "", encoding="utf-8")
    return image_relative.as_posix(), label_relative.as_posix()


def stage_public_sources(config: dict[str, Any], stage: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    cache = resolve_path(config["cache"])
    exact: dict[str, dict[str, Any]] = {}
    signatures: list[tuple[int, dict[str, Any]]] = []
    buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
    for source_name, source in sorted(config["sources"].items(), key=lambda item: item[1]["priority"]):
        archive = cache / f"{source_name}-v{source['version']}.zip"
        if not archive.is_file():
            quarantine.append({"source": source_name, "reason": "archive_not_downloaded"})
            continue
        with tempfile.TemporaryDirectory(prefix=f"safesight-{source_name}-", dir=resolve_path(config["workspace"])) as temporary:
            extracted = Path(temporary)
            safe_extract(archive, extracted)
            names = names_from_yaml(extracted)
            for image in iter_export_images(extracted):
                label = label_for(image)
                record = {"source": source_name, "publisher_sample_id": image.stem}
                try:
                    if label is None or not label.is_file():
                        raise ValueError("matching label file is missing")
                    with Image.open(image) as opened:
                        opened.load()
                        if min(opened.size) < 16:
                            raise ValueError("image dimensions are too small")
                        signature = dhash(opened)
                    boxes, ignored = parse_labels(label, names, source["class_aliases"])
                    reasons = audit_boxes(boxes)
                    if reasons:
                        raise ValueError(",".join(reasons))
                    image_hash = digest(image)
                    label_value = "\n".join(box.line() for box in boxes)
                    if image_hash in exact:
                        if exact[image_hash]["label_value"] != label_value:
                            raise ValueError("exact_duplicate_has_conflicting_labels")
                        continue
                    candidates: set[int] = set()
                    for shift in range(4):
                        candidates.update(buckets[(shift, (signature >> (shift * 16)) & 65535)])
                    near = next(
                        (
                            signatures[index][1]
                            for index in candidates
                            if (signature ^ signatures[index][0]).bit_count() <= 3
                            and visually_near(image, stage / signatures[index][1]["path"])
                        ),
                        None,
                    )
                    if near is not None:
                        raise ValueError(f"near_duplicate_of:{near['path']}")
                    path, annotation = copy_sample(image, boxes, source_name, image.stem, stage)
                    record.update({
                        "sample_id": Path(path).stem, "path": path, "annotation": annotation,
                        "source_id": f"{source_name}:{image.stem}", "group_id": scene_group(source_name, image.stem),
                        "publisher": source_name, "license": source["license"], "ignored_other_boxes": ignored,
                        "image_sha256": image_hash, "perceptual_hash": f"{signature:016x}", "label_value": label_value,
                    })
                    exact[image_hash] = record
                    index = len(signatures)
                    signatures.append((signature, record))
                    for shift in range(4):
                        buckets[(shift, (signature >> (shift * 16)) & 65535)].append(index)
                    accepted.append(record)
                except (OSError, ValueError, UnicodeError) as error:
                    record["reason"] = str(error)
                    quarantine.append(record)
    return accepted, quarantine


def add_dfire_replay(config: dict[str, Any], stage: Path, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    replay = config["replay"]
    source = resolve_path(replay["source"])
    manifest = source / "manifest.jsonl"
    if not manifest.is_file():
        return [{"source": "dfire_replay", "reason": "source_manifest_missing"}]
    rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    candidates = [row for row in rows if row.get("publisher") == "dfire"]
    rng = random.Random(42)
    strata: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        try:
            boxes, _ = parse_labels(within(source, row["annotation"]), ["smoke", "fire"], {"smoke": "smoke", "fire": "fire"})
            classes = {box.class_id for box in boxes}
            category = "both" if classes == {0, 1} else "smoke" if classes == {0} else "fire" if classes == {1} else "negative"
            strata[category].append(row)
        except (OSError, ValueError, KeyError):
            continue
    quota = int(replay["maximum_images"]) // 4
    selected: list[dict[str, Any]] = []
    for category in ("fire", "smoke", "both", "negative"):
        rng.shuffle(strata[category])
        selected.extend(strata[category][:quota])
    existing_hashes = {record["image_sha256"] for record in records}
    rejected: list[dict[str, Any]] = []
    for row in selected:
        image, label = within(source, row["path"]), within(source, row["annotation"])
        try:
            image_hash = digest(image)
            if image_hash in existing_hashes:
                continue
            boxes, _ = parse_labels(label, ["smoke", "fire"], {"smoke": "smoke", "fire": "fire"})
            if audit_boxes(boxes):
                raise ValueError(",".join(audit_boxes(boxes)))
            path, annotation = copy_sample(image, boxes, "dfire_replay", image.stem, stage)
            record = {
                "sample_id": Path(path).stem, "path": path, "annotation": annotation,
                "source_id": row["source_id"], "group_id": row["group_id"], "publisher": "dfire_replay",
                "publisher_sample_id": row.get("publisher_sample_id", image.stem), "license": row["license"],
                "image_sha256": image_hash,
            }
            records.append(record)
            existing_hashes.add(image_hash)
        except (OSError, ValueError, KeyError) as error:
            rejected.append({"source": "dfire_replay", "path": row.get("path"), "reason": str(error)})
    return rejected


def contact_sheets(stage: Path, records: list[dict[str, Any]], destination: Path) -> int:
    """Render deterministic annotation samples without changing the corpus."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        boxes, _ = parse_labels(stage / record["annotation"], ["smoke", "fire"], {"smoke": "smoke", "fire": "fire"})
        classes = {box.class_id for box in boxes}
        for class_id, name in ((0, "smoke"), (1, "fire")):
            if class_id in classes:
                groups[(record["publisher"], name)].append(record)
        if not classes:
            groups[(record["publisher"], "negative")].append(record)
    rng = random.Random(42)
    destination.mkdir(parents=True, exist_ok=True)
    count = 0
    for (publisher, category), rows in sorted(groups.items()):
        rng.shuffle(rows)
        for page_index in range(0, min(100, len(rows)), 25):
            canvas = Image.new("RGB", (1280, 1000), "#15191f")
            for cell, record in enumerate(rows[page_index:page_index + 25]):
                with Image.open(stage / record["path"]) as opened:
                    image = opened.convert("RGB")
                boxes, _ = parse_labels(stage / record["annotation"], ["smoke", "fire"], {"smoke": "smoke", "fire": "fire"})
                image.thumbnail((246, 172))
                x0, y0 = (cell % 5) * 256 + 5, (cell // 5) * 200 + 20
                canvas.paste(image, (x0, y0))
                draw = ImageDraw.Draw(canvas)
                for box in boxes:
                    left = x0 + (box.x - box.width / 2) * image.width
                    top = y0 + (box.y - box.height / 2) * image.height
                    right = x0 + (box.x + box.width / 2) * image.width
                    bottom = y0 + (box.y + box.height / 2) * image.height
                    draw.rectangle((left, top, right, bottom), outline="#52d273" if box.class_id == 0 else "#ff5757", width=2)
                draw.text((x0, y0 - 15), record["sample_id"][:35], fill="white")
            canvas.save(destination / f"{publisher}-{category}-{page_index // 25 + 1}.jpg", quality=88)
            count += 1
    return count


def build(config: dict[str, Any], replace: bool = False) -> dict[str, Any]:
    workspace = resolve_path(config["workspace"])
    workspace.mkdir(parents=True, exist_ok=True)
    missing = [
        name
        for name, source in config["sources"].items()
        if not (resolve_path(config["cache"]) / f"{name}-v{source['version']}.zip").is_file()
    ]
    if missing:
        raise ValueError("Cannot finalize an incomplete corpus; missing archives: " + ", ".join(missing))
    stage = workspace / "staged-corpus"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    records, quarantine = stage_public_sources(config, stage)
    quarantine.extend(add_dfire_replay(config, stage, records))
    for record in records:
        record.pop("label_value", None)
    manifest = "".join(json.dumps(record, sort_keys=True) + "\n" for record in records)
    (stage / "manifest.jsonl").write_text(manifest, encoding="utf-8")
    (stage / "data.yaml").write_text("path: .\ntrain: images\nval: images\ntest: images\nnames: [smoke, fire]\n", encoding="utf-8")
    attribution = ["# Curated fire/smoke corpus attribution", ""]
    for name, source in sorted(config["sources"].items(), key=lambda item: item[1]["priority"]):
        attribution.append(f"- {name}: {source['url']} — {source['license']} — project {source['project']} v{source['version']}")
    attribution.append("- dfire_replay: provenance and license are retained per manifest row from the existing SafeSight corpus.")
    (stage / "ATTRIBUTION.md").write_text("\n".join(attribution) + "\n", encoding="utf-8")
    sheet_count = contact_sheets(stage, records, workspace / "audit" / "contact-sheets")
    report = {
        "schema_version": 1, "accepted": len(records), "quarantined": len(quarantine),
        "by_source": dict(Counter(record["publisher"] for record in records)),
        "quarantine_reasons": dict(Counter(record.get("reason", "unknown").split(":", 1)[0] for record in quarantine)),
        "manifest_sha256": hashlib.sha256(manifest.encode()).hexdigest(), "contact_sheets": sheet_count,
        "training_executed": False,
    }
    write_json(workspace / "audit" / "report.json", report)
    write_json(workspace / "audit" / "quarantine.json", quarantine)
    output = resolve_path(config["output"])
    if output.exists():
        if not replace:
            raise ValueError(f"Output already exists; preserve it or rerun with --replace: {output}")
        backup = output.with_name(output.name + ".previous")
        if backup.exists():
            raise ValueError(f"Backup already exists: {backup}")
        output.rename(backup)
    stage.replace(output)
    write_json(output / "preparation.json", report)
    return report


def target_review(config: dict[str, Any]) -> dict[str, Any]:
    settings = config["target_review"]
    source = resolve_path(settings["source"])
    workspace = resolve_path(config["workspace"])
    destination = workspace / "target_review"
    staging = workspace / "target_review-staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    videos = sorted(path for path in source.glob("*") if path.is_file())
    maximum = int(settings["maximum_frames"])
    per_video = max(1, maximum // max(1, len(videos)))
    rows: list[dict[str, Any]] = []
    for video in videos:
        previous: int | None = None
        kept = 0
        next_time = 0.0
        try:
            with av.open(str(video)) as container:
                stream = container.streams.video[0]
                # Review frames do not need every inter-frame prediction decoded.
                # Keyframes preserve broad scene diversity and keep HDD scans bounded.
                stream.codec_context.skip_frame = "NONKEY"
                for frame in container.decode(stream):
                    timestamp = float(frame.time or 0.0)
                    if timestamp + 1e-6 < next_time:
                        continue
                    image = frame.to_image().convert("RGB")
                    signature = dhash(image)
                    if previous is not None and (previous ^ signature).bit_count() < int(settings["perceptual_distance"]):
                        continue
                    stem = f"{video.stem}-{timestamp:010.3f}".replace(".", "_")
                    image_path = staging / "images" / f"{stem}.jpg"
                    label_path = staging / "labels" / f"{stem}.txt"
                    image_path.parent.mkdir(parents=True, exist_ok=True)
                    label_path.parent.mkdir(parents=True, exist_ok=True)
                    image.save(image_path, quality=92)
                    label_path.write_text("", encoding="utf-8")
                    rows.append({"image": image_path.relative_to(staging).as_posix(), "label": label_path.relative_to(staging).as_posix(), "source_video": video.name, "timestamp": timestamp, "status": "REVIEW_REQUIRED"})
                    kept += 1
                    previous = signature
                    next_time = timestamp + float(settings["minimum_interval_seconds"])
                    if kept >= per_video or len(rows) >= maximum:
                        break
        except (OSError, av.error.FFmpegError, IndexError) as error:
            rows.append({"source_video": video.name, "status": "DECODE_FAILED", "reason": str(error)})
        if len(rows) >= maximum:
            break
    manifest = staging / "review_manifest.jsonl"
    manifest.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    if destination.exists():
        backup = workspace / "target_review.previous"
        if backup.exists():
            shutil.rmtree(backup)
        destination.replace(backup)
    staging.replace(destination)
    return {"frames": sum(row["status"] == "REVIEW_REQUIRED" for row in rows), "videos": len(videos), "path": str(destination)}


def prelabel_target(config: dict[str, Any]) -> dict[str, Any]:
    """Seed the review queue with current-model boxes; never promote them to training."""
    from ultralytics import YOLO
    import torch

    review = resolve_path(config["workspace"]) / "target_review"
    manifest_path = review / "review_manifest.jsonl"
    if not manifest_path.is_file():
        raise ValueError("Create the target review set before pre-labeling it")
    card_path = ROOT / "models" / "fire_smoke" / "model_card.json"
    card = json.loads(card_path.read_text(encoding="utf-8"))
    if card.get("classes") != ["smoke", "fire"]:
        raise ValueError("Installed fire/smoke model has an incompatible class order")
    artifact = within(ROOT / "models", card["artifact"])
    model = YOLO(str(artifact))
    rows = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    pending = [row for row in rows if row.get("status") == "REVIEW_REQUIRED"]
    sidecar: list[dict[str, Any]] = []
    for offset in range(0, len(pending), 4):
        batch_rows = pending[offset:offset + 4]
        predictions = model.predict(
            [str(within(review, row["image"])) for row in batch_rows],
            imgsz=int(card.get("input_size", 640)),
            conf=0.05,
            iou=float(card.get("postprocessing", {}).get("nms_iou", 0.45)),
            device=0 if torch.cuda.is_available() else "cpu",
            verbose=False,
        )
        for row, result in zip(batch_rows, predictions):
            boxes: list[Box] = []
            detections: list[dict[str, Any]] = []
            for coordinates, score, class_id in zip(
                result.boxes.xywhn.cpu().tolist(), result.boxes.conf.cpu().tolist(), result.boxes.cls.cpu().tolist()
            ):
                class_index = int(class_id)
                box = Box(class_index, *map(float, coordinates))
                boxes.append(box)
                detections.append({"class": card["classes"][class_index], "confidence": float(score), "box": coordinates})
            within(review, row["label"]).write_text(
                ("\n".join(box.line() for box in boxes) + "\n") if boxes else "", encoding="utf-8"
            )
            row["status"] = "PRELABELED_REVIEW_REQUIRED"
            sidecar.append({"image": row["image"], "detections": detections})
    manifest_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    (review / "prelabel_predictions.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in sidecar), encoding="utf-8"
    )
    return {"images": len(pending), "detections": sum(len(row["detections"]) for row in sidecar), "review_required": True}


def preflight(config: dict[str, Any]) -> dict[str, Any]:
    output = resolve_path(config["output"])
    cache = resolve_path(config["cache"])
    free = shutil.disk_usage(str(ROOT)).free
    key_present = bool(os.getenv("ROBOFLOW_API_KEY", "").strip())
    return {
        "output": str(output), "cache": str(cache), "free_gb": round(free / 1024**3, 2),
        "minimum_free_gb": config["minimum_free_gb"], "roboflow_key_present": key_present,
        "expected_source_images": sum(int(source["expected_images"]) for source in config["sources"].values()),
        "sources": {name: {"project": value["project"], "version": value["version"], "license": value["license"]} for name, value in config["sources"].items()},
    }


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("preflight", "download", "build", "target-review", "prelabel-target", "all"))
    parser.add_argument("--config", default="configs/fire_smoke_curated_sources.yaml")
    parser.add_argument("--source", action="append", help="Limit download to a configured source name")
    parser.add_argument("--replace", action="store_true", help="Move an existing curated corpus aside before finalizing")
    args = parser.parse_args(argv)
    config = read_yaml(args.config)
    if config.get("schema_version") != 1:
        parser.error("Unsupported curation config schema")
    result: dict[str, Any] = {"preflight": preflight(config)}
    print(json.dumps(result["preflight"], indent=2))
    if result["preflight"]["free_gb"] < float(config["minimum_free_gb"]):
        raise SystemExit("Insufficient free disk space")
    if args.phase in ("download", "all"):
        result["download"] = acquire(config, set(args.source or []) or None)
    if args.phase in ("target-review", "all"):
        result["target_review"] = target_review(config)
    if args.phase in ("prelabel-target", "all"):
        result["target_prelabels"] = prelabel_target(config)
    if args.phase in ("build", "all"):
        result["build"] = build(config, args.replace)
    write_json(resolve_path(config["workspace"]) / "last_run.json", result)
    print(json.dumps(result, indent=2))
    print("No training was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
