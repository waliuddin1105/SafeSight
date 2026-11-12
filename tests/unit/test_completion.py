"""Acceptance checks for M0-M7 that never execute a training loop."""

from collections import deque

import numpy as np
import pytest

from safesight.config import read_yaml
from safesight.contracts import Candidate, Detection, Prediction
from safesight.inference.engine import Engine, Temporal
from safesight.inference.state import dumps, loads
from safesight.inference.state import blob_references
from safesight.model_loaders.registry import entrance_frame
from training.common.detection_metrics import size_ap
from training.common.evaluation import calibrate, replay


def test_entrance_crop_uses_only_configured_region():
    image = np.zeros((50, 100, 3), dtype=np.uint8)
    image[:, 50:] = 255
    assert entrance_frame(image, 32, [0, 0, 0.5, 1]).max() == 0
    assert entrance_frame(image, 32, [0.5, 0, 1, 1]).min() == 255
    with pytest.raises(ValueError):
        entrance_frame(image, 32, [0.5, 0, 0.2, 1])


def test_recovery_restores_ids_history_and_media():
    policy = read_yaml("configs/inference.yaml")
    engine = Engine(policy)
    person = Detection("person", 0.9, (0, 0, 1, 1))
    engine.tracker.update([person], 0)
    engine.temporal.step([Candidate("fire_smoke", "fire", "scene", 0.9, 0)], 0, {})
    state = {"engine": engine, "media": deque([(0, b"jpeg")], maxlen=10), "array": np.zeros((5, 5, 3), dtype=np.uint8)}
    restored = loads(dumps(state))
    assert restored["media"].maxlen == 10
    assert restored["engine"].tracker.tracks["person1"][0].label == "person"
    alert = restored["engine"].temporal.step([Candidate("fire_smoke", "fire", "scene", 0.9, 0.2)], 0.2, {})
    assert alert
    assert restored["array"].shape == (5, 5, 3)


def test_recovery_rejects_executable_types():
    with pytest.raises(ValueError):
        dumps(object())


def test_recovery_externalizes_media_without_rewriting_windows():
    import hashlib

    blocks = {}

    def put(data):
        digest = hashlib.sha256(data).hexdigest()
        blocks[digest] = data
        return digest

    payload = dumps({"a": b"jpeg", "b": np.zeros((128, 128, 3), dtype=np.uint8)}, put)
    assert len(payload) < 1000
    assert len(blob_references(payload)) == 2
    restored = loads(payload, blocks.__getitem__)
    assert restored["a"] == b"jpeg"
    assert restored["b"].shape == (128, 128, 3)


def test_safe_frames_break_persistence():
    policy = read_yaml("configs/inference.yaml")
    temporal = Temporal(policy)
    temporal.step([Candidate("phone_usage", "phone_usage", "p", 0.9, 0)], 0, {}, {"phone_usage"})
    temporal.step([], 0.2, {}, {"phone_usage"})
    assert not temporal.step([Candidate("phone_usage", "phone_usage", "p", 0.9, 0.4)], 0.4, {}, {"phone_usage"})


def test_n_of_m_allows_a_negative_between_positive_observations():
    temporal = Temporal(read_yaml("configs/inference.yaml"))
    assert not temporal.step([Candidate("fire_smoke", "fire", "scene", 0.9, 0)], 0, {}, {"fire_smoke"})
    assert not temporal.step([], 0.2, {}, {"fire_smoke"})
    assert temporal.step([Candidate("fire_smoke", "fire", "scene", 0.9, 0.4)], 0.4, {}, {"fire_smoke"})


def test_small_object_ap_is_measured_and_missing_is_undefined():
    record = {
        "width": 100,
        "height": 100,
        "targets": [{"class_id": 0, "box": [0.1, 0.1, 0.2, 0.2]}],
        "predictions": [{"class_id": 0, "score": 0.9, "box": [0.1, 0.1, 0.2, 0.2]}],
    }
    result = size_ap([record], ["cigarette"])
    assert result["small"]["ap50"] == 1
    assert result["large"]["ap50"] is None


def test_calibration_cannot_pass_on_one_positive():
    policy = read_yaml("configs/inference.yaml")
    observations = []
    for t in (0, 0.2, 0.4):
        observations.append((t, Prediction("fire_smoke", t, detections=[Detection("fire", 0.9, (0, 0, 1, 1))]), []))
    cached = [
        {
            "group_id": "one",
            "events": [{"subtype": "fire", "start": 0, "end": 1}],
            "duration": 1,
            "observations": observations,
        }
    ]
    thresholds, _ = calibrate(cached, "fire_smoke", policy, 0.9)
    assert thresholds["fire"] > 1


def test_joint_replay_never_suppresses_strong_fire():
    observations = []
    for t in (0, 0.2, 0.4):
        observations.append(
            (
                t,
                [
                    Prediction("cigarette_smoking", t, detections=[Detection("cigarette", 0.99, (0.4, 0.4, 0.5, 0.5))]),
                    Prediction("fire_smoke", t, detections=[Detection("fire", 0.99, (0, 0, 1, 1))]),
                ],
                [],
            )
        )
    cached = [
        {
            "group_id": "one",
            "events": [{"subtype": "fire", "start": 0, "end": 1}],
            "duration": 1,
            "observations": observations,
        }
    ]
    measured = replay(cached, "fire_smoke", read_yaml("configs/inference.yaml"), {"fire": 0.5})
    assert measured["categories"]["fire"]["tp"] == 1
    assert measured["categories"]["fire"]["mean_delay_seconds"] == 0.2
