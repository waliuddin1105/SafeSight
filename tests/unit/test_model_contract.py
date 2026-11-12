"""Artifact replacement and policy checks using untrained, explicit test modules."""

import hashlib
import json

import torch

from safesight.contracts import CLASSES
from safesight.model_loaders.registry import Registry


class FixedClassifier(torch.nn.Module):
    """Deterministic fixture; no optimizer or training is involved."""

    def __init__(self, direction: float):
        super().__init__()
        self.register_buffer("bias", torch.arange(5, dtype=torch.float32) * direction)

    def forward(self, points: torch.Tensor) -> torch.Tensor:
        return self.bias.unsqueeze(0).expand(points.shape[0], -1)


def test_replacement_requires_only_artifact_and_card(tmp_path, monkeypatch):
    monkeypatch.setattr("safesight.model_loaders.registry.PoseExtractor", lambda asset: None)

    # Body context is supplied by a harmless fixture object; this test exercises loading.
    class Pose:
        def close(self):
            pass

    monkeypatch.setattr("safesight.model_loaders.registry.PoseExtractor", lambda asset: Pose())
    (tmp_path / "_pretrained").mkdir()
    (tmp_path / "_pretrained/pose_landmarker_lite.task").write_bytes(b"pose-test-fixture")
    folder = tmp_path / "body_state"
    folder.mkdir()
    for number, direction in enumerate((1.0, -1.0)):
        artifact = folder / f"model{number}.ts"
        torch.jit.script(FixedClassifier(direction)).save(str(artifact))
        card = {
            "slug": "body_state",
            "loader": "torchscript",
            "architecture": "test_fixture",
            "classes": CLASSES["body_state"],
            "artifact": artifact.relative_to(tmp_path).as_posix(),
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "run_id": str(number),
            "input_size": 32,
            "thresholds": {},
            "quality": {"status": "FAIL", "reasons": ["untrained test fixture"]},
            "synthetic": True,
        }
        (folder / "model_card.json").write_text(json.dumps(card))
        registry = Registry(
            tmp_path, evaluation=True, device="cpu", selected={"body_state": "body_state/model_card.json"}
        )
        try:
            assert registry.status["body_state"]["ready"]
            scores = registry.adapters["body_state"].model(torch.zeros((1, 33, 4)))
            assert scores.argmax(-1).item() == (4 if direction > 0 else 0)
        finally:
            registry.close()
    card["sha256"] = "0" * 64
    (folder / "model_card.json").write_text(json.dumps(card))
    registry = Registry(tmp_path, evaluation=True, device="cpu", selected={"body_state": "body_state/model_card.json"})
    assert not registry.status["body_state"]["ready"]
    registry.close()
