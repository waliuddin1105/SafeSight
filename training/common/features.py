"""Content-addressed, disk-backed frozen representations with integrity checks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import torch
from torch.utils.data import Dataset

from safesight.config import ROOT
from training.common.datasets import jsonl, sha256


class FeatureDataset(Dataset):
    """Read one representation at a time, keeping dataset size out of RAM."""

    def __init__(self, directory: Path, rows: list[dict]):
        self.directory, self.rows = directory, rows
        self.labels = torch.tensor([r["label"] for r in rows], dtype=torch.long)

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int):
        row = self.rows[index]
        return torch.load(self.directory / row["file"], map_location="cpu", weights_only=True)


class FeatureWriter:
    """Write independently reusable tensor samples instead of retaining a list."""

    def __init__(self, directory: Path, split: str):
        self.directory, self.split, self.rows = directory, split, []

    def append(self, sample: tuple) -> None:
        name = f"{self.split}_{len(self.rows):08d}.pt"
        path = self.directory / name
        temporary = path.with_suffix(".partial")
        torch.save(sample, temporary)
        temporary.replace(path)
        self.rows.append({"file": name, "label": int(sample[1]), "sha256": sha256(path)})


def feature_cache(config: dict, dataset: Path, network, run: Path) -> tuple[Path, dict | None]:
    """Fingerprint source bytes, preprocessing, frozen encoder and augmentation seed."""
    digest = hashlib.sha256()
    settings = {
        k: config.get(k)
        for k in ("slug", "architecture", "image_size", "sequence_length", "sequence_fps", "seed", "smoke")
    }
    digest.update(json.dumps(settings, sort_keys=True).encode())
    digest.update((Path(__file__).parent / "runner.py").read_bytes())
    for source in (Path(__file__), Path(__file__).parent / "networks.py", ROOT / "safesight/model_loaders/registry.py"):
        digest.update(source.read_bytes())
    for row in jsonl(dataset / "manifest.jsonl"):
        digest.update(json.dumps(row, sort_keys=True).encode())
        for name in (row["path"], row["annotation"]):
            digest.update(sha256(dataset / name).encode())
    if hasattr(network, "encoder"):
        for name, tensor in network.encoder.state_dict().items():
            digest.update(name.encode())
            digest.update(tensor.detach().cpu().numpy().tobytes())
    else:
        asset = Path(config["pretrained_root"])
        if not asset.is_absolute():
            asset = ROOT / asset
        pose = asset / "pose_landmarker_lite.task"
        expected = json.loads((ROOT / "models/assets.json").read_text())["pose_landmarker_lite.task"]["sha256"]
        digest.update((sha256(pose) if pose.exists() else expected).encode())
    key = digest.hexdigest()
    directory = (
        ROOT / ("tests/fixtures/features" if config.get("smoke") else "artifacts/features") / config["slug"] / key
    )
    directory.mkdir(parents=True, exist_ok=True)
    reference = run / "feature-cache.json"
    if reference.exists() and json.loads(reference.read_text())["fingerprint"] != key:
        raise ValueError("Feature cache changed; resume rejected")
    reference.write_text(json.dumps({"fingerprint": key}), encoding="utf-8")
    index = directory / "index.json"
    if not index.exists():
        return directory, None
    rows = json.loads(index.read_text(encoding="utf-8"))
    for split in rows.values():
        for row in split:
            if sha256(directory / row["file"]) != row["sha256"]:
                raise ValueError("Frozen feature cache checksum mismatch")
    return directory, {split: FeatureDataset(directory, records) for split, records in rows.items()}


def accumulation_weight(index: int, total: int, batch: int, samples: int, accumulation: int) -> float:
    """Weight a mean batch loss by its exact share of the accumulation group."""
    start = (index // accumulation) * accumulation * batch
    group_samples = min(accumulation * batch, samples - start)
    current_samples = min(batch, samples - index * batch)
    return current_samples / group_samples
