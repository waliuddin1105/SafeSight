"""Behavior checks for temporal gaps and model qualification."""

from safesight.config import read_yaml, ROOT
from safesight.contracts import Candidate, Detection, Prediction
from safesight.inference.engine import Engine, Temporal
from safesight.model_loaders.registry import Registry


def test_temporal_persistence_and_gap():
    policy = read_yaml("configs/inference.yaml")
    temporal = Temporal(policy)

    def step(t):
        return temporal.step([Candidate("fire_smoke", "fire", "scene", 0.9, t)], t, {})

    assert not step(0)
    first = step(0.2)[0]
    assert step(0.4)[0].event_id == first.event_id
    assert not step(3)


def test_lighter_alone_does_not_imply_smoking():
    engine = Engine(read_yaml("configs/inference.yaml"))
    person = Detection("person", 0.99, (0.1, 0.1, 0.9, 0.9))
    prediction = Prediction(
        "cigarette_smoking", 0, detections=[person, Detection("lighter", 0.99, (0.4, 0.4, 0.5, 0.5))]
    )
    for t in (0, 0.2, 0.4, 0.6):
        assert not engine.process([prediction], [person], t)


def test_synthetic_models_rejected_in_production():
    registry = Registry(ROOT / "tests/fixtures/models", evaluation=False, device="cpu")
    try:
        assert not registry.adapters
        assert all(not state["ready"] for state in registry.status.values())
    finally:
        registry.close()
