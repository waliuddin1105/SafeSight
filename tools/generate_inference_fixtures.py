"""Create explicitly untrained runtime artifacts for checks without running trainers."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys

import torch
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from safesight.contracts import CLASSES, YOLO_SLUGS  # noqa: E402
from tools.fetch_pretrained import fetch  # noqa: E402


class BodyFixture(torch.nn.Module):
    """Shape-correct test logits; no learned safety capability is claimed."""

    def forward(self, points: torch.Tensor) -> torch.Tensor:
        return torch.zeros((points.shape[0], 5), device=points.device)


class EntranceFixture(torch.nn.Module):
    """Shape-correct sequence test logits; no optimization is performed."""

    def forward(self, frames: torch.Tensor, lengths: torch.Tensor) -> torch.Tensor:
        return torch.zeros((frames.shape[0], 4), device=frames.device)


def generate() -> Path:
    """Build deterministic, synthetic-only fixtures independently of all train.py files."""
    root = ROOT / "tests/fixtures/inference-models"
    if (root / "fixture.json").exists():
        return root
    torch.manual_seed(42)
    torch.set_num_threads(2)
    from ultralytics import YOLO
    from ultralytics.nn.tasks import DetectionModel
    from ultralytics.utils import DEFAULT_CFG_DICT
    import ultralytics

    config = yaml.safe_load((Path(ultralytics.__file__).parent / "cfg/models/11/yolo11.yaml").read_text())
    config["scale"] = "n"
    for slug, classes in CLASSES.items():
        directory = root / slug
        directory.mkdir(parents=True, exist_ok=True)
        if slug in YOLO_SLUGS:
            model = YOLO("yolo11n.yaml", task="detect", verbose=False)
            model.model = DetectionModel(copy.deepcopy(config), nc=len(classes), verbose=False)
            model.model.names = dict(enumerate(classes))
            model.model.args = {**DEFAULT_CFG_DICT, "task": "detect"}
            artifact = directory / "untrained.pt"
            model.save(str(artifact))
        else:
            artifact = directory / "untrained.ts"
            torch.jit.script(BodyFixture() if slug == "body_state" else EntranceFixture()).save(str(artifact))
        card = {
            "schema_version": 1,
            "slug": slug,
            "loader": "ultralytics" if slug in YOLO_SLUGS else "torchscript",
            "architecture": "untrained_inference_fixture",
            "classes": classes,
            "artifact": artifact.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "run_id": "untrained-inference-fixture-v1",
            "input_size": 128,
            "sequence_length": 10,
            "sequence_fps": 5,
            "thresholds": {"uncertain_smoke": 1.01},
            "quality": {"status": "FAIL", "reasons": ["Untrained synthetic runtime fixture; no quality metrics exist"]},
            "synthetic": True,
        }
        (directory / "model_card.json").write_text(json.dumps(card, indent=2))
    (root / "_pretrained").mkdir(exist_ok=True)
    pose = fetch("pose_landmarker_lite.task")
    target = root / "_pretrained/pose_landmarker_lite.task"
    if pose.resolve() != target.resolve():
        shutil.copyfile(pose, target)
    (root / "fixture.json").write_text(json.dumps({"synthetic": True, "trained": False, "seed": 42}))
    return root


if __name__ == "__main__":
    print(generate())
