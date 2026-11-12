"""Build immutable, reproducible source-group splits outside user datasets."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import yaml

from safesight.config import ROOT, within
from safesight.contracts import CLASSES, YOLO_SLUGS
from training.common.datasets import jsonl, sha256


def split_for_group(group_id: str, seed: int = 42, ratios: tuple[float, ...] = (0.7, 0.15, 0.15)) -> str:
    """Stable assignment independent of input order and use-case name."""
    if len(ratios) != 3 or any(r <= 0 for r in ratios) or abs(sum(ratios) - 1) > 1e-8:
        raise ValueError("Split ratios must be three positive values summing to one")
    value = int(hashlib.sha256(f"{seed}:{group_id}".encode()).hexdigest(), 16) / 2**256
    return "train" if value < ratios[0] else "val" if value < sum(ratios[:2]) else "test"


def materialize_splits(
    root: Path,
    slug: str,
    seed: int = 42,
    ratios: tuple[float, ...] = (0.7, 0.15, 0.15),
    output_root: Path | None = None,
) -> Path:
    """Accept legacy split datasets or stage a flat manifest and events.jsonl.

    Flat records omit `split`; mixed/manual and automatic assignments are rejected.
    Caller still runs full validation before training. No source file is changed.
    """
    manifest = root / "manifest.jsonl"
    if not manifest.is_file():
        return root  # Existing validator supplies the actionable missing-file error.
    records = jsonl(manifest)
    if not records or all(row.get("split") in ("train", "val", "test") for row in records):
        return root
    if any("split" in row for row in records):
        raise ValueError("Automatic splitting requires all manifest rows to omit split")
    folder = "clips" if slug == "entrance_guard" else "images"
    actual = {p.relative_to(root).as_posix() for p in (root / folder).rglob("*") if p.is_file()}
    listed = {row["path"] for row in records}
    if actual - listed:
        raise ValueError("Input media missing from manifest; add provenance before splitting")
    events = jsonl(root / "events.jsonl") if (root / "events.jsonl").is_file() else []
    rows = records + events
    # Both scene/session and source identity constrain partitions. Refuse inconsistent
    # grouping rather than silently break cross-task consistency with a guessed union.
    source_groups: dict[str, str] = {}
    assignments = {}
    for row in rows:
        group, source = row.get("group_id"), row.get("source_id")
        if not isinstance(group, str) or not group or not isinstance(source, str) or not source:
            raise ValueError("Every sample/event video needs a real source_id and group_id")
        if source in source_groups and source_groups[source] != group:
            raise ValueError(f"Source {source} has multiple group_ids; consolidate its recording session")
        source_groups[source] = group
        assignments[group] = split_for_group(group, seed, ratios)
    fingerprint = hashlib.sha256(json.dumps({"slug": slug, "seed": seed, "ratios": ratios}, sort_keys=True).encode())
    paths = {"manifest.jsonl"}
    if events:
        paths.add("events.jsonl")
    if slug in YOLO_SLUGS:
        data = yaml.safe_load((root / "data.yaml").read_text(encoding="utf-8"))
        names = data["names"]
        if isinstance(names, dict):
            names = [names[i] for i in range(len(names))]
        if names != CLASSES[slug] or data.get("download"):
            raise ValueError("data.yaml must declare the approved classes and no download script")
        paths.add("data.yaml")
    for row in records:
        paths.update((row["path"], row["annotation"]))
    paths.update(row["video"] for row in events)
    for name in sorted(paths):
        path = within(root, name)
        fingerprint.update(name.encode())
        fingerprint.update(sha256(path).encode())
    destination = (output_root or ROOT / "artifacts/dataset-splits") / slug / fingerprint.hexdigest()
    marker = destination / "split_plan.json"
    if marker.exists():
        plan = json.loads(marker.read_text(encoding="utf-8"))
        for name, checksum in plan["files"].items():
            if sha256(within(destination, name)) != checksum:
                raise ValueError("Generated split was modified; restore it or use a fresh artifact directory")
        return destination
    if destination.exists():
        raise ValueError(f"Incomplete split staging at {destination}; remove that generated directory and retry")
    destination.mkdir(parents=True)
    written = set()

    def copy(name: str, output: str) -> None:
        if output in written:
            raise ValueError(f"Duplicate destination in split: {output}")
        written.add(output)
        target = within(destination, output)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(within(root, name), target)

    staged = []
    folder = "clips" if slug == "entrance_guard" else "images"
    annotation_folder = "labels" if slug in YOLO_SLUGS else "annotations"
    for row in records:
        split = assignments[row["group_id"]]
        # Preserve nested paths; require the documented flat input roots.
        media = Path(row["path"])
        annotation = Path(row["annotation"])
        if media.parts[0] != folder or annotation.parts[0] != annotation_folder:
            raise ValueError(f"Use {folder}/ and {annotation_folder}/ for unsplit inputs")
        output_media = f"{folder}/{split}/" + Path(*media.parts[1:]).as_posix()
        output_annotation = f"{annotation_folder}/{split}/" + Path(*annotation.parts[1:]).as_posix()
        copy(row["path"], output_media)
        copy(row["annotation"], output_annotation)
        staged.append({**row, "path": output_media, "annotation": output_annotation, "split": split})
    (destination / "manifest.jsonl").write_text("".join(json.dumps(row) + "\n" for row in staged), encoding="utf-8")
    if slug in YOLO_SLUGS:
        (destination / "data.yaml").write_text(
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
    if slug != "entrance_guard":
        for split in ("val", "test"):
            selected = []
            for row in events:
                if assignments[row["group_id"]] == split:
                    name = Path(row["video"])
                    if name.parts[0] != "videos":
                        raise ValueError("Event videos must be under videos/")
                    output = f"videos/{split}/" + Path(*name.parts[1:]).as_posix()
                    copy(row["video"], output)
                    selected.append({**row, "video": output})
            path = destination / "events" / f"{split}.jsonl"
            path.parent.mkdir(exist_ok=True)
            path.write_text("".join(json.dumps(row) + "\n" for row in selected), encoding="utf-8")
    files = {p.relative_to(destination).as_posix(): sha256(p) for p in destination.rglob("*") if p.is_file()}
    marker.write_text(
        json.dumps({"seed": seed, "ratios": ratios, "groups": assignments, "files": files}, indent=2), encoding="utf-8"
    )
    return destination
