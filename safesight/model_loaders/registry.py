"""Model-card-only loading; runtime never downloads weights or imports trainers."""

from __future__ import annotations

import hashlib
import copy
import logging
from collections import deque
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np
import torch
from safesight.config import within
from safesight.contracts import CLASSES, Detection, Prediction
from safesight.contracts.model_card import ModelCard

LOG = logging.getLogger(__name__)


def file_sha256(path: Path) -> str:
    """Hash large model files without loading them into API or worker memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def select_device(requested: str = "auto") -> str:
    """Probe CUDA with a real operation; missing or incompatible CUDA falls back to CPU."""
    if requested == "cpu":
        return "cpu"
    try:
        if torch.cuda.is_available():
            device = "cuda:0" if requested == "auto" else requested
            (torch.ones(1, device=device) * 2).cpu()
            return device
    except (RuntimeError, AssertionError) as error:
        LOG.warning("CUDA probe failed, using CPU: %s", error)
    LOG.info("Using CPU; a working CUDA installation is optional")
    return "cpu"


class Adapter(Protocol):
    """Any supported model returns the same prediction contract."""

    card: ModelCard

    def predict(self, rgb: np.ndarray, timestamp: float) -> Prediction: ...


def _intersection_over_smaller(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """Measure how completely the smaller normalized box is covered."""
    intersection = max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0.0, min(a[3], b[3]) - max(a[1], b[1])
    )
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    smaller = min(area_a, area_b)
    return intersection / smaller if smaller else 0.0


def deduplicate_detections(
    detections: list[Detection],
    iou_threshold: float = 0.45,
    containment_threshold: float = 0.8,
) -> list[Detection]:
    """Keep the strongest box in each same-class overlap cluster.

    Ordinary NMS does not always remove a small box nested inside a much larger
    box because their IoU can remain low. The containment check handles that
    case without suppressing legitimate overlap between different classes.
    """
    from safesight.inference.engine import iou

    kept: list[Detection] = []
    for detection in sorted(detections, key=lambda item: item.score, reverse=True):
        duplicate = any(
            detection.label == previous.label
            and (
                iou(detection.box, previous.box) >= iou_threshold
                or _intersection_over_smaller(detection.box, previous.box) >= containment_threshold
            )
            for previous in kept
        )
        if not duplicate:
            kept.append(detection)
    return kept


def letterbox(rgb: np.ndarray, size: int) -> np.ndarray:
    """Aspect-preserving resize used identically for train and runtime sequences."""
    h, w = rgb.shape[:2]
    ratio = size / max(h, w)
    nw, nh = max(1, round(w * ratio)), max(1, round(h * ratio))
    result = np.zeros((size, size, 3), dtype=np.uint8)
    x, y = (size - nw) // 2, (size - nh) // 2
    result[y : y + nh, x : x + nw] = cv2.resize(rgb, (nw, nh))
    return result


def entrance_frame(rgb: np.ndarray, size: int, roi: list | None = None) -> np.ndarray:
    """Apply the same normalized entrance crop in collection, evaluation and runtime."""
    roi = roi or [0, 0, 1, 1]
    if len(roi) != 4 or not 0 <= roi[0] < roi[2] <= 1 or not 0 <= roi[1] < roi[3] <= 1:
        raise ValueError("Entrance ROI must be normalized xyxy")
    height, width = rgb.shape[:2]
    crop = rgb[int(roi[1] * height) : max(1, int(roi[3] * height)), int(roi[0] * width) : max(1, int(roi[2] * width))]
    if not crop.size:
        raise ValueError("Entrance ROI contains no pixels")
    return letterbox(crop, size)


class PoseExtractor:
    """Frozen MediaPipe Tasks extractor; no trained body classifier dependency."""

    def __init__(self, asset: Path):
        import mediapipe as mp

        if not asset.is_file():
            raise FileNotFoundError(f"Pose asset missing: {asset}; use tools/fetch_pretrained.py")
        self.asset_hash = file_sha256(asset)
        self.mp = mp
        self.model = mp.tasks.vision.PoseLandmarker.create_from_options(
            mp.tasks.vision.PoseLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=str(asset)),
                num_poses=10,
                min_pose_detection_confidence=0.5,
                min_pose_presence_confidence=0.5,
            )
        )

    def extract(self, rgb: np.ndarray) -> list[Detection]:
        result = self.model.detect(self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
        people = []
        for points in result.pose_landmarks:
            array = np.array([[p.x, p.y, p.z, p.visibility] for p in points], dtype=np.float32)
            visible = array[:, 3] >= 0.5
            if visible.sum() < 8:
                continue
            xy = np.clip(array[visible, :2], 0, 1)
            box = (*xy.min(axis=0), *xy.max(axis=0))
            people.append(
                Detection("person", float(array[visible, 3].mean()), tuple(map(float, box)), keypoints=array.tolist())
            )
        return people

    def close(self) -> None:
        self.model.close()


class YoloAdapter:
    def __init__(self, card: ModelCard, artifact: Path, device: str):
        from ultralytics import YOLO

        self.card, self.device = card, device
        postprocessing = (card.model_extra or {}).get("postprocessing", {})
        self.nms_iou = float(postprocessing.get("nms_iou", 0.45))
        self.containment_threshold = float(postprocessing.get("containment_threshold", 0.8))
        if not 0 < self.nms_iou <= 1 or not 0 < self.containment_threshold <= 1:
            raise ValueError("Detection post-processing thresholds must be in (0, 1]")
        self.model = YOLO(str(artifact), task="detect")
        if list(self.model.names.values()) != card.classes:
            raise ValueError("Weights and model-card classes differ")

    def predict(self, rgb: np.ndarray, timestamp: float) -> Prediction:
        return self.predict_batch([rgb], [timestamp])[0]

    def predict_batch(self, images: list[np.ndarray], timestamps: list[float]) -> list[Prediction]:
        """Batch detector work while preserving input order and per-frame coordinates."""
        if len(images) != len(timestamps) or not images:
            raise ValueError("Images and timestamps must be nonempty and aligned")
        results = self.model.predict(
            [rgb[:, :, ::-1] for rgb in images],
            imgsz=self.card.input_size,
            device=self.device,
            conf=0.01,
            iou=self.nms_iou,
            agnostic_nms=False,
            verbose=False,
        )
        detections_by_frame = [
            [Detection(self.card.classes[int(c)], float(s), tuple(map(float, b)))
             for b, s, c in zip(result.boxes.xyxyn.cpu().tolist(), result.boxes.conf.cpu().tolist(), result.boxes.cls.cpu().tolist())]
            for result in results
        ]
        if self.card.slug == "cigarette_smoking":
            crop_images, crop_origins = [], []
            for frame_index, (rgb, detections) in enumerate(zip(images, detections_by_frame)):
                height, width = rgb.shape[:2]
                for person in detections:
                    if person.label != "person" or person.score < 0.25:
                        continue
                    x1, y1, x2, y2 = person.box
                    padding = 0.2
                    left = max(0, int((x1 - padding * (x2 - x1)) * width))
                    top = max(0, int((y1 - padding * (y2 - y1)) * height))
                    right = min(width, int((x2 + padding * (x2 - x1)) * width))
                    bottom = min(height, int((y2 + padding * (y2 - y1)) * height))
                    if right - left < 16 or bottom - top < 16:
                        continue
                    crop_images.append(rgb[top:bottom, left:right, ::-1])
                    crop_origins.append((frame_index, left, top, right, bottom, width, height))
            if crop_images:
                crop_results = self.model.predict(
                    crop_images, imgsz=self.card.input_size, device=self.device,
                    conf=0.01, verbose=False,
                )
            else:
                crop_results = []
            for crop, (frame_index, left, top, right, bottom, width, height) in zip(crop_results, crop_origins):
                detections = detections_by_frame[frame_index]
                for box, score, class_id in zip(
                    crop.boxes.xyxyn.cpu().tolist(), crop.boxes.conf.cpu().tolist(), crop.boxes.cls.cpu().tolist()
                ):
                    label = self.card.classes[int(class_id)]
                    if label == "person":
                        continue
                    mapped = (
                        (left + box[0] * (right - left)) / width,
                        (top + box[1] * (bottom - top)) / height,
                        (left + box[2] * (right - left)) / width,
                        (top + box[3] * (bottom - top)) / height,
                    )
                    from safesight.inference.engine import iou

                    if not any(d.label == label and iou(d.box, mapped) > 0.5 and d.score >= score for d in detections):
                        detections.append(Detection(label, float(score), mapped))
        return [
            Prediction(self.card.slug, timestamp,
                detections=deduplicate_detections(detections, self.nms_iou, self.containment_threshold),
                model_version=self.card.run_id)
            for timestamp, detections in zip(timestamps, detections_by_frame)
        ]


class TorchAdapter:
    def __init__(self, card: ModelCard, artifact: Path, device: str, pose: PoseExtractor | None):
        self.card, self.device, self.pose = card, device, pose
        self.model = torch.jit.load(str(artifact), map_location=device).eval()
        self.buffer: deque[tuple[float, np.ndarray]] = deque(maxlen=card.sequence_length)
        self.frames_seen = 0
        self.source_config: dict = {}

    def predict(self, rgb: np.ndarray, timestamp: float, people: list[Detection] | None = None) -> Prediction:
        if self.card.slug == "body_state":
            if self.pose is None:
                return Prediction(self.card.slug, timestamp, unknown_reason="Pose extractor unavailable")
            if people is None:
                people = self.pose.extract(rgb)
            if not people:
                return Prediction(self.card.slug, timestamp, unknown_reason="No visible pose")
            tensor = torch.tensor([p.keypoints for p in people], dtype=torch.float32, device=self.device)
            with torch.inference_mode():
                probabilities = self.model(tensor).softmax(-1).cpu().numpy()
            detections = [
                Detection(
                    self.card.classes[int(values.argmax())], float(values.max()), person.box, keypoints=person.keypoints
                )
                for person, values in zip(people, probabilities)
            ]
            return Prediction(self.card.slug, timestamp, detections=detections, model_version=self.card.run_id)
        if self.buffer and (timestamp <= self.buffer[-1][0] or timestamp - self.buffer[-1][0] > 1):
            self.buffer.clear()
            self.frames_seen = 0
        if not self.buffer or timestamp - self.buffer[-1][0] >= 1 / self.card.sequence_fps - 0.01:
            self.buffer.append(
                (timestamp, entrance_frame(rgb, self.card.input_size, self.source_config.get("entrance_roi")))
            )
            self.frames_seen += 1
        if len(self.buffer) < min(self.card.sequence_length, int(self.card.sequence_fps * 2)):
            return Prediction(self.card.slug, timestamp, unknown_reason="Collecting entrance observation window")
        # The window is expensive; evaluate once per second while retaining every frame.
        stride = max(1, round(self.card.sequence_fps))
        if self.frames_seen % stride:
            return Prediction(self.card.slug, timestamp, unknown_reason="Collecting entrance observation window")
        array = np.stack([frame for _, frame in self.buffer]).transpose(0, 3, 1, 2).astype(np.float32) / 255
        with torch.inference_mode():
            scores = (
                self.model(
                    torch.from_numpy(array).unsqueeze(0).to(self.device), torch.tensor([len(array)], device=self.device)
                )
                .softmax(-1)[0]
                .cpu()
                .tolist()
            )
        return Prediction(
            self.card.slug, timestamp, scores=dict(zip(self.card.classes, scores)), model_version=self.card.run_id
        )


class Registry:
    """Load configured task artifacts and preserve explicit per-task failure status."""

    def __init__(
        self,
        root: Path,
        evaluation: bool = False,
        device: str = "auto",
        selected: dict[str, str] | None = None,
        pose_asset: str = "_pretrained/pose_landmarker_lite.task",
        cards: dict | None = None,
        reusable: Registry | None = None,
    ):
        self.root, self.evaluation = root.resolve(), evaluation
        self.device = select_device(device)
        self.adapters: dict[str, Adapter] = {}
        self.status: dict[str, dict] = {}
        self.pose: PoseExtractor | None = None
        pose_path = within(self.root, pose_asset)
        self.owns_pose = True
        selected_slugs = set(selected) if selected is not None else {
            slug for slug in CLASSES if (self.root / slug / "model_card.json").is_file()
        }
        if pose_path.exists() and selected_slugs.intersection({"body_state", "phone_usage", "cigarette_smoking", "entrance_guard"}):
            pose_hash = file_sha256(pose_path)
            if (
                reusable is not None
                and reusable.pose is not None
                and getattr(reusable.pose, "asset_hash", None) == pose_hash
            ):
                self.pose, self.owns_pose = reusable.pose, False
            else:
                self.pose = PoseExtractor(pose_path)
        for slug in selected if selected is not None else CLASSES:
            relative_card = (selected or {}).get(slug, f"{slug}/model_card.json")
            card_path = within(self.root, relative_card)
            if cards is None and not card_path.is_file():
                version_cards = sorted((self.root / slug / "versions").glob("*/model_card.json"))
                if selected is None:
                    if version_cards:
                        count = len(version_cards)
                        reason = (
                            f"No production model is active; {count} installed version"
                            f"{'s are' if count != 1 else ' is'} available for explicit video testing"
                        )
                    else:
                        reason = "No model has been installed for this use case"
                else:
                    reason = "The selected model version is not installed on this device"
                self.status[slug] = {
                    "ready": False,
                    "reason": reason,
                    "available_versions": [path.parent.name for path in version_cards],
                }
                continue
            try:
                card = (
                    ModelCard.model_validate(cards[slug])
                    if cards is not None
                    else ModelCard.model_validate_json(card_path.read_text(encoding="utf-8"))
                )
                if (
                    card.schema_version != 1
                    or card.preprocessing != "v1"
                    or card.slug != slug
                    or card.classes != CLASSES[slug]
                ):
                    raise ValueError("Incompatible model card schema/classes/preprocessing")
                expected_context = (card.model_extra or {}).get("context_asset_sha256")
                if expected_context is not None and (
                    not pose_path.is_file() or file_sha256(pose_path) != expected_context
                ):
                    raise ValueError("Preprocessing pose asset differs from the calibrated model context")
                if slug in ("body_state", "phone_usage", "cigarette_smoking", "entrance_guard") and self.pose is None:
                    raise ValueError("Required pretrained pose context asset is missing")
                if (card.synthetic or card.quality.get("status") != "PASS") and not evaluation:
                    raise ValueError("Model failed production gate; explicit evaluation mode required")
                artifact = within(self.root, card.artifact)
                if not artifact.is_file():
                    raise ValueError("Model artifact referenced by the card is not installed on this device")
                if file_sha256(artifact) != card.sha256:
                    raise ValueError("Model artifact checksum mismatch")
                existing = (
                    reusable.adapters.get(slug) if reusable is not None and reusable.device == self.device else None
                )
                if existing is not None and existing.card.model_dump() == card.model_dump():
                    adapter = existing
                elif card.loader == "ultralytics":
                    adapter = YoloAdapter(card, artifact, self.device)
                elif card.loader == "torchscript":
                    adapter = TorchAdapter(card, artifact, self.device, self.pose)
                else:
                    raise ValueError(f"Unsupported loader: {card.loader}")
                self.adapters[slug] = adapter
                self.status[slug] = {
                    "ready": True,
                    "run_id": card.run_id,
                    "quality": card.quality,
                    "synthetic": card.synthetic,
                    "evaluation_only": card.synthetic or card.quality.get("status") != "PASS",
                }
            except (OSError, ValueError, RuntimeError, KeyError) as error:
                self.status[slug] = {"ready": False, "reason": str(error)}

    def close(self) -> None:
        if self.pose and self.owns_pose:
            self.pose.close()

    def temporal_policy(self, fallback: dict) -> dict:
        """Use each artifact's calibrated behavior, rejecting incompatible fusion policies."""
        result = copy.deepcopy(fallback)
        global_policies = []
        for slug, adapter in self.adapters.items():
            policy = adapter.card.model_extra.get("temporal_policy", {}) if adapter.card.model_extra else {}
            if policy:
                result[slug] = copy.deepcopy(policy[slug])
                global_policies.append({k: v for k, v in policy.items() if k not in CLASSES})
        if global_policies:
            if all(p == global_policies[0] for p in global_policies):
                result.update(global_policies[0])
            else:
                LOG.warning("Model global temporal policies differ; retaining configured shared policy")
        from safesight.contracts.configuration import validate_policy

        return validate_policy(result)
