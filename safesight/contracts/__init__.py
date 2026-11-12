"""Versioned task and inference contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

CLASSES = {
    "body_state": ["upright", "seated", "crouching_kneeling", "deep_bend", "lying_on_floor"],
    "phone_usage": ["person", "phone"],
    "cigarette_smoking": ["person", "cigarette", "lighter", "smoke"],
    "entrance_guard": ["verified_entry", "unverified_entry", "no_entry", "indeterminate"],
    "fire_smoke": ["fire", "smoke", "person"],
}
SLUGS = tuple(CLASSES)
YOLO_SLUGS = ("phone_usage", "cigarette_smoking", "fire_smoke")


@dataclass
class Detection:
    """A normalized box and score; optional keypoints use image coordinates."""

    label: str
    score: float
    box: tuple[float, float, float, float]
    track_id: str | None = None
    keypoints: list[list[float]] | None = None


@dataclass
class Prediction:
    """One task's result for a timestamped frame."""

    slug: str
    timestamp: float
    detections: list[Detection] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    unknown_reason: str | None = None
    model_version: str = ""


@dataclass
class Candidate:
    """A temporal decision candidate, before event suppression."""

    slug: str
    subtype: str
    track_id: str
    score: float
    timestamp: float
    uncertain: bool = False
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class Alert:
    """A detected incident interval emitted by the temporal engine."""

    candidate: Candidate
    start: float
    end: float
    event_id: str
