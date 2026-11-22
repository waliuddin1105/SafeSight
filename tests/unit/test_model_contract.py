"""Artifact replacement and policy checks using untrained, explicit test modules."""

import hashlib
import json

import torch

from safesight.contracts import CLASSES
from safesight.model_loaders.registry import Registry, YoloAdapter, ModelCard


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


def test_missing_active_cards_report_portable_actionable_status(tmp_path):
    version = tmp_path / "fire_smoke/versions/evaluation-run"
    version.mkdir(parents=True)
    (version / "model_card.json").write_text("{}", encoding="utf-8")

    registry = Registry(tmp_path, evaluation=False, device="cpu")
    try:
        assert registry.status["body_state"] == {
            "ready": False,
            "reason": "No model has been installed for this use case",
            "available_versions": [],
        }
        assert registry.status["fire_smoke"] == {
            "ready": False,
            "reason": "No production model is active; 1 installed version is available for explicit video testing",
            "available_versions": ["evaluation-run"],
        }
        assert str(tmp_path) not in registry.status["fire_smoke"]["reason"]
    finally:
        registry.close()


def test_missing_selected_card_and_artifact_do_not_expose_device_paths(tmp_path):
    missing = Registry(
        tmp_path,
        evaluation=True,
        device="cpu",
        selected={"fire_smoke": "fire_smoke/versions/missing/model_card.json"},
    )
    assert missing.status["fire_smoke"]["reason"] == "The selected model version is not installed on this device"
    missing.close()

    folder = tmp_path / "fire_smoke/versions/imported"
    folder.mkdir(parents=True)
    card = {
        "slug": "fire_smoke",
        "loader": "ultralytics",
        "architecture": "fixture",
        "classes": CLASSES["fire_smoke"],
        "artifact": "fire_smoke/versions/imported/missing.pt",
        "sha256": "0" * 64,
        "run_id": "imported",
        "input_size": 32,
        "thresholds": {},
        "quality": {"status": "FAIL"},
    }
    (folder / "model_card.json").write_text(json.dumps(card), encoding="utf-8")
    registry = Registry(
        tmp_path,
        evaluation=True,
        device="cpu",
        selected={"fire_smoke": "fire_smoke/versions/imported/model_card.json"},
    )
    assert registry.status["fire_smoke"]["reason"] == (
        "Model artifact referenced by the card is not installed on this device"
    )
    registry.close()


def test_smoking_batch_maps_crop_boxes_to_each_original_frame():
    import numpy as np

    class Values:
        def __init__(self, values):
            self.values = values

        def cpu(self):
            return self

        def tolist(self):
            return self.values

    class Result:
        def __init__(self, boxes, scores, classes):
            self.boxes = type("Boxes", (), {
                "xyxyn": Values(boxes), "conf": Values(scores), "cls": Values(classes)
            })()

    class Detector:
        def __init__(self):
            self.calls = []

        def predict(self, images, **kwargs):
            self.calls.append(len(images))
            if len(self.calls) == 1:
                return [Result([[0.1, 0.1, 0.5, 0.9]], [0.9], [0]) for _ in images]
            return [Result([[0.5, 0.5, 0.6, 0.6]], [0.8], [1]) for _ in images]

    adapter = YoloAdapter.__new__(YoloAdapter)
    adapter.card = ModelCard(
        slug="cigarette_smoking", loader="ultralytics", architecture="fixture",
        classes=CLASSES["cigarette_smoking"], artifact="fixture.pt", sha256="0" * 64,
        run_id="fixture", input_size=64, thresholds={}, quality={"status": "FAIL"},
    )
    adapter.model, adapter.device = Detector(), "cpu"
    adapter.nms_iou, adapter.containment_threshold = 0.45, 0.8
    predictions = adapter.predict_batch([np.zeros((100, 100, 3), dtype=np.uint8)] * 2, [0.0, 0.2])
    assert adapter.model.calls == [2, 2]
    assert [prediction.timestamp for prediction in predictions] == [0.0, 0.2]
    assert all(any(d.label == "cigarette" and d.box[0] > 0.2 for d in p.detections) for p in predictions)
