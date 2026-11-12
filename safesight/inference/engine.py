"""Independent predictions fused into timestamp-aware, reviewable incidents."""

from __future__ import annotations

import math
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any


from safesight.contracts import Alert, Candidate, Detection, Prediction


def iou(a: tuple | list, b: tuple | list) -> float:
    """Intersection over union for normalized xyxy boxes."""
    overlap = max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    return overlap / max(1e-9, (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - overlap)


def center(box: tuple | list) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


class Tracker:
    """Greedy IoU tracks with explicit ambiguity and expiry."""

    def __init__(self, minimum_iou: float = 0.25, ttl: float = 2):
        self.minimum_iou, self.ttl = minimum_iou, ttl
        self.tracks: dict[str, tuple[Detection, float]] = {}
        self.counter = 0

    def update(self, people: list[Detection], timestamp: float) -> tuple[list[Detection], bool]:
        self.tracks = {key: value for key, value in self.tracks.items() if timestamp - value[1] <= self.ttl}
        used, ambiguous = set(), False
        for person in people:
            matches = sorted(
                [(iou(person.box, previous.box), key) for key, (previous, _) in self.tracks.items() if key not in used],
                reverse=True,
            )
            if len(matches) > 1 and matches[1][0] > self.minimum_iou and matches[0][0] - matches[1][0] < 0.1:
                ambiguous = True
            if matches and matches[0][0] >= self.minimum_iou:
                key = matches[0][1]
            else:
                self.counter += 1
                key = f"person{self.counter}"
            person.track_id = key
            self.tracks[key] = (person, timestamp)
            used.add(key)
        return people, ambiguous


@dataclass
class TemporalState:
    observations: deque = field(default_factory=deque)
    first: float = 0
    last: float = 0
    emitted: bool = False
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))


class Temporal:
    """N-of-M observations with duration, gaps, and event cooldown."""

    def __init__(self, config: dict):
        self.config = config
        self.states: dict[tuple, TemporalState] = {}
        self.cooldowns: dict[tuple, float] = {}

    def step(
        self,
        candidates: list[Candidate],
        timestamp: float,
        thresholds: dict[str, dict],
        known_slugs: set[str] | None = None,
    ) -> list[Alert]:
        alerts = []
        current = {}
        for candidate in candidates:
            key = (candidate.slug, candidate.subtype, candidate.track_id)
            if key not in current or candidate.score > current[key].score:
                current[key] = candidate
        gap = self.config.get("max_gap_seconds", 1.0)
        for key in list(self.states):
            if timestamp - self.states[key].last > gap:
                ended = self.states.pop(key)
                if ended.emitted:
                    self.cooldowns[key] = ended.last + self.config.get("cooldown_seconds", 10)
            elif key not in current and known_slugs is not None and key[0] in known_slugs:
                state = self.states[key]
                state.observations.append((timestamp, False))
                state.last = timestamp
                while len(state.observations) > self.config[key[0]]["m"]:
                    state.observations.popleft()
                if sum(value for _, value in state.observations) < self.config[key[0]]["n"]:
                    if state.emitted:
                        self.cooldowns[key] = timestamp + self.config.get("cooldown_seconds", 10)
                        state.emitted = False
                        state.event_id = str(uuid.uuid4())
                    if not any(value for _, value in state.observations):
                        self.states.pop(key)
                if self.config[key[0]].get("durations", {}).get(key[1], 0):
                    state.first = timestamp
        for key, candidate in current.items():
            rule = self.config[candidate.slug]
            threshold = thresholds.get(candidate.slug, {}).get(candidate.subtype, 0.5)
            positive = candidate.score >= threshold
            state = self.states.setdefault(key, TemporalState(first=timestamp, last=timestamp))
            state.last = timestamp
            state.observations.append((timestamp, positive))
            while len(state.observations) > rule["m"]:
                state.observations.popleft()
            duration = rule.get("durations", {}).get(candidate.subtype, 0)
            enough = sum(value for _, value in state.observations) >= rule["n"]
            if not positive:
                if not enough:
                    state.first = timestamp
                    if state.emitted:
                        self.cooldowns[key] = timestamp + self.config.get("cooldown_seconds", 10)
                        state.emitted = False
                        state.event_id = str(uuid.uuid4())
                    if not any(value for _, value in state.observations):
                        self.states.pop(key)
                continue
            if enough and timestamp - state.first + 1e-6 >= duration and timestamp >= self.cooldowns.get(key, -1):
                state.emitted = True
                alerts.append(Alert(candidate, state.first, timestamp, state.event_id))
        return alerts


class Engine:
    """One engine per source; no temporal state is shared between cameras."""

    def __init__(self, config: dict, thresholds: dict[str, dict] | None = None, source: dict | None = None):
        self.config, self.thresholds, self.source = config, thresholds or {}, source or {}
        self.tracker = Tracker(config.get("tracking_iou", 0.25), config.get("tracking_ttl_seconds", 2))
        self.temporal = Temporal(config)
        self.cues: dict[str, dict[str, Any]] = defaultdict(dict)
        self.previous_y: dict[str, float] = {}
        self.pending_crossings: dict[str, tuple[float, Detection]] = {}
        self.smoke_area = 0.0
        self.previous_time: float | None = None
        self.unknown: dict[str, str] = {}

    @staticmethod
    def owner(item: Detection, people: list[Detection]) -> Detection | None:
        x, y = center(item.box)
        candidates = [
            person
            for person in people
            if person.box[0] - 0.1 <= x <= person.box[2] + 0.1 and person.box[1] - 0.1 <= y <= person.box[3] + 0.1
        ]
        return max(candidates, key=lambda person: iou(item.box, person.box), default=None)

    @staticmethod
    def hand_near(item: Detection, person: Detection) -> bool:
        if not person.keypoints:
            return False
        x, y = center(item.box)
        scale = max(0.1, person.box[3] - person.box[1])
        return any(
            p[3] >= 0.5 and math.dist((x, y), p[:2]) <= scale * 0.18
            for p in [person.keypoints[15], person.keypoints[16]]
        )

    def candidates(self, predictions: list[Prediction], people: list[Detection], timestamp: float) -> list[Candidate]:
        by_slug = {p.slug: p for p in predictions}
        self.unknown = {p.slug: p.unknown_reason for p in predictions if p.unknown_reason}
        if not people:
            for prediction in predictions:
                for detection in prediction.detections:
                    if (
                        detection.label == "person"
                        and detection.score >= 0.25
                        and not any(iou(detection.box, p.box) > 0.5 for p in people)
                    ):
                        people.append(detection)
        people, ambiguous = self.tracker.update(people, timestamp)
        if ambiguous:
            self.temporal.states.clear()
            self.cues.clear()
            self.unknown["entrance_guard"] = "Ambiguous track reassignment"
        result: list[Candidate] = []

        def add(
            slug: str, subtype: str, person: Detection | None, score: float, uncertain: bool = False, **details: Any
        ) -> None:
            result.append(
                Candidate(
                    slug,
                    subtype,
                    person.track_id if person and person.track_id else "scene",
                    float(score),
                    timestamp,
                    uncertain,
                    {"box": list(person.box) if person else details.pop("box", None), **details},
                )
            )

        body = by_slug.get("body_state")
        if body and not body.unknown_reason:
            for detection in body.detections:
                person = max(people, key=lambda p: iou(p.box, detection.box), default=None)
                if (
                    person
                    and iou(person.box, detection.box) > 0.1
                    and detection.label in self.config["body_state"]["durations"]
                ):
                    add("body_state", detection.label, person, detection.score)
        phone = by_slug.get("phone_usage")
        if phone:
            for detection in phone.detections:
                if detection.label != "phone":
                    continue
                person = self.owner(detection, people)
                if person and self.hand_near(detection, person):
                    add("phone_usage", "phone_usage", person, detection.score, cues=["phone", "hand_proximity"])
                elif person:
                    self.unknown["phone_usage"] = "Phone present but hand interaction is not observable"
        smoking = by_slug.get("cigarette_smoking")
        smoking_people = set()
        if smoking:
            memory = self.config["cigarette_smoking"].get("cue_memory_seconds", 4)
            for person in people:
                cue = self.cues[person.track_id]
                hand_mouth = False
                if person.keypoints:
                    nose = person.keypoints[0]
                    scale = max(0.1, person.box[3] - person.box[1])
                    hand_mouth = nose[3] >= 0.5 and any(
                        p[3] >= 0.5 and math.dist(p[:2], nose[:2]) < scale * 0.15
                        for p in [person.keypoints[15], person.keypoints[16]]
                    )
                if hand_mouth and not cue.get("hand_mouth_active"):
                    cue.setdefault("gestures", []).append(timestamp)
                cue["hand_mouth_active"] = hand_mouth
                cue["gestures"] = [t for t in cue.get("gestures", []) if timestamp - t <= memory]
                nearby = [d for d in smoking.detections if self.owner(d, [person])]
                for detection in nearby:
                    if detection.label == "lighter" and self.hand_near(detection, person):
                        cue["lighter"] = (timestamp, detection.score)
                    if detection.label == "cigarette" and (self.hand_near(detection, person) or hand_mouth):
                        add(
                            "cigarette_smoking",
                            "smoking",
                            person,
                            detection.score,
                            cues=["cigarette", "hand_or_mouth"],
                            hidden_cigarette=False,
                        )
                        if detection.score >= self.thresholds.get("cigarette_smoking", {}).get("smoking", 0.5):
                            smoking_people.add(person.track_id)
                smoke = max(
                    (
                        d.score
                        for d in nearby
                        if d.label == "smoke"
                        and center(d.box)[1] < person.box[1] + 0.5 * (person.box[3] - person.box[1])
                    ),
                    default=0,
                )
                lighter = cue.get("lighter", (-100.0, 0.0))
                if smoke and timestamp - lighter[0] <= memory and len(cue["gestures"]) >= 2:
                    add(
                        "cigarette_smoking",
                        "smoking",
                        person,
                        min(smoke, lighter[1]),
                        cues=["lighter", "repeated_hand_mouth", "localized_smoke"],
                        hidden_cigarette=True,
                    )
                    if min(smoke, lighter[1]) >= self.thresholds.get("cigarette_smoking", {}).get("smoking", 0.5):
                        smoking_people.add(person.track_id)
        fire = by_slug.get("fire_smoke")
        if fire:
            area = sum(
                (d.box[2] - d.box[0]) * (d.box[3] - d.box[1])
                for d in fire.detections
                if d.label == "smoke" and d.score >= 0.1
            )
            growing = self.smoke_area > 0 and area / self.smoke_area >= self.config["fire_smoke"].get(
                "growth_ratio", 1.25
            )
            flames = any(d.label == "fire" and d.score >= 0.25 for d in fire.detections)
            for detection in fire.detections:
                if detection.label == "fire":
                    add("fire_smoke", "fire", None, detection.score, box=list(detection.box), cues=["flame"])
                elif detection.label == "smoke":
                    person = self.owner(detection, people)
                    tobacco = self.source.get("fusion_enabled", True) and person and person.track_id in smoking_people
                    spread = growing or area > 0.15
                    if flames or spread:
                        add(
                            "fire_smoke",
                            "hazardous_smoke",
                            None,
                            detection.score,
                            box=list(detection.box),
                            cues=["smoke", "flame_or_spread"],
                        )
                    elif not tobacco:
                        add(
                            "fire_smoke",
                            "uncertain_smoke",
                            None,
                            detection.score,
                            True,
                            box=list(detection.box),
                            cues=["unresolved_smoke_source"],
                        )
            self.smoke_area = area
        guard = by_slug.get("entrance_guard")
        if guard:
            line = self.source.get("crossing_line_y", 0.75)
            guard_region = self.source.get("guard_region", [0, 0, 0.3, 1])
            entrants = [
                p
                for p in people
                if not (
                    guard_region[0] <= center(p.box)[0] <= guard_region[2]
                    and guard_region[1] <= center(p.box)[1] <= guard_region[3]
                )
            ]
            if len(entrants) > 1 or ambiguous:
                self.unknown["entrance_guard"] = "Multiple or ambiguous entrants"
                self.pending_crossings.clear()
            for person in entrants:
                y = person.box[3]
                previous = self.previous_y.get(person.track_id)
                crossing = previous is not None and previous < line <= y
                self.previous_y[person.track_id] = y
                if crossing and len(entrants) == 1 and not ambiguous:
                    self.pending_crossings[person.track_id] = (timestamp, person)
            for track_id, (crossing_time, person) in list(self.pending_crossings.items()):
                if timestamp - crossing_time >= self.config["entrance_guard"].get("post_crossing_seconds", 2):
                    del self.pending_crossings[track_id]
                    if guard.unknown_reason or max(guard.scores, key=guard.scores.get, default="indeterminate") in (
                        "indeterminate",
                        "no_entry",
                    ):
                        self.unknown["entrance_guard"] = "Crossing observed but procedure is indeterminate"
                    else:
                        add(
                            "entrance_guard",
                            "unverified_entry",
                            person,
                            guard.scores.get("unverified_entry", 0),
                            cues=["crossing", "sequence_classification"],
                        )
        return result

    def process(self, predictions: list[Prediction], people: list[Detection], timestamp: float) -> list[Alert]:
        if self.previous_time is not None and (
            timestamp <= self.previous_time or timestamp - self.previous_time > self.config.get("max_gap_seconds", 1)
        ):
            self.temporal = Temporal(self.config)
            self.cues.clear()
            self.previous_y.clear()
            self.pending_crossings.clear()
            self.tracker.tracks.clear()
        self.previous_time = timestamp
        candidates = self.candidates(predictions, people, timestamp)
        return self.temporal.step(
            candidates, timestamp, self.thresholds, {p.slug for p in predictions if not p.unknown_reason}
        )
