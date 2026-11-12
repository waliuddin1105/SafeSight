"""Shared registered-asset download code used by independent trainers."""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
import urllib.request
from safesight.config import ROOT, settings


def fetch(name: str, destination: Path | None = None) -> Path:
    """Fetch one pinned asset; unpinned registry entries are rejected."""
    registry = json.loads((ROOT / "models/assets.json").read_text(encoding="utf-8"))
    asset = registry[name]
    expected = asset["sha256"]
    if not expected:
        raise ValueError(f"Asset checksum is not pinned: {name}")
    root = destination or settings()["models_root"] / "_pretrained"
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == expected:
        return path
    temporary = path.with_suffix(path.suffix + ".download")
    with urllib.request.urlopen(asset["url"], timeout=60) as response, temporary.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    actual = hashlib.sha256(temporary.read_bytes()).hexdigest()
    if actual != expected:
        temporary.unlink()
        raise ValueError(f"Checksum mismatch for {name}: expected {expected}, got {actual}")
    temporary.replace(path)
    return path
