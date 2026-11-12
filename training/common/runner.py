"""Independent training lifecycle: validate, fit, calibrate, test, report, publish."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import logging
import math
import os
import random
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset
from sklearn.metrics import classification_report, confusion_matrix, f1_score
import yaml

from safesight.config import ROOT, read_yaml, resolve_path
from safesight.contracts import CLASSES, YOLO_SLUGS
from safesight.ingestion.video import frames
from safesight.model_loaders.registry import PoseExtractor, Registry, entrance_frame, select_device
from training.common.assets import fetch
from training.common.checkpoints import restore_state
from training.common.datasets import jsonl, sha256, validate
from training.common.evaluation import cache_predictions, calibrate, quality_gate, replay
from training.common.fixtures import generate
from training.common.detection_metrics import evaluate_sizes
from training.common.provenance import source_identity
from training.common.reports import dataset_inventory, failure_gallery
from training.common.networks import BodyMLP, EntranceLSTM
from training.common.features import FeatureDataset, FeatureWriter, feature_cache, accumulation_weight

LOG = logging.getLogger(__name__)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def save_checkpoint(path: Path, state: dict) -> None:
    """Atomically replace the last complete classifier checkpoint."""
    temporary = path.with_suffix(".partial.pt")
    torch.save(state, temporary)
    temporary.replace(path)


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(min(4, os.cpu_count() or 1))
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False
    torch.use_deterministic_algorithms(True, warn_only=True)


def stage_yolo(dataset: Path, destination: Path, slug: str) -> Path:
    """Copy labels and link media outside datasets; library caches stay in staging."""
    rows = jsonl(dataset / "manifest.jsonl")
    class_counts = np.zeros(len(CLASSES[slug]))
    for row in rows:
        if row["split"] == "train":
            for line in (dataset / row["annotation"]).read_text().splitlines():
                if line.strip():
                    class_counts[int(line.split()[0])] += 1
    for row in rows:
        image = dataset / row["path"]
        label = dataset / row["annotation"]
        lines = [line for line in label.read_text().splitlines() if line.strip()]
        classes = [int(line.split()[0]) for line in lines]
        repeat = (
            min(3, max(1, math.ceil(class_counts.max() / max(1, min(class_counts[classes])))))
            if classes and row["split"] == "train"
            else 1
        )
        for index in range(repeat):
            name = hashlib.sha256((row["sample_id"] + row["path"]).encode()).hexdigest()[:24] + f"_{index}"
            image_target = destination / "images" / row["split"] / (name + image.suffix)
            label_target = destination / "labels" / row["split"] / (name + ".txt")
            image_target.parent.mkdir(parents=True, exist_ok=True)
            label_target.parent.mkdir(parents=True, exist_ok=True)
            if not image_target.exists():
                # Isolate third-party JPEG repair/cache behavior from user media.
                shutil.copyfile(image, image_target)
            shutil.copyfile(label, label_target)
        if slug == "cigarette_smoking" and row["split"] == "train":
            with Image.open(image) as opened:
                w, h = opened.size
                boxes = [list(map(float, line.split())) for line in lines]
                for index, (class_id, x, y, bw, bh) in enumerate(boxes):
                    if int(class_id) != 0:
                        continue
                    left, top, right, bottom = (
                        max(0, x - bw * 0.7),
                        max(0, y - bh * 0.7),
                        min(1, x + bw * 0.7),
                        min(1, y + bh * 0.7),
                    )
                    crop_labels = []
                    for cid, cx, cy, cw, ch in boxes:
                        x1, y1, x2, y2 = cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2
                        if left <= x1 < x2 <= right and top <= y1 < y2 <= bottom:
                            crop_labels.append(
                                f"{int(cid)} {(cx - left) / (right - left)} {(cy - top) / (bottom - top)} {cw / (right - left)} {ch / (bottom - top)}"
                            )
                    crop_name = (
                        hashlib.sha256((row["sample_id"] + row["path"]).encode()).hexdigest()[:24] + f"_crop_{index}"
                    )
                    opened.crop((int(left * w), int(top * h), int(right * w), int(bottom * h))).save(
                        destination / "images/train" / f"{crop_name}.jpg"
                    )
                    (destination / "labels/train" / f"{crop_name}.txt").write_text("\n".join(crop_labels))
    data = {
        "path": str(destination.resolve()),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "names": CLASSES[slug],
    }
    path = destination / "data.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def fit_yolo(config: dict, dataset: Path, run: Path, device: str, resume: Path | None) -> tuple[Path, Any]:
    from ultralytics import YOLO, settings

    settings.update(
        {
            "datasets_dir": str(ROOT / "artifacts/dataset-cache"),
            "weights_dir": str(resolve_path(config["pretrained_root"])),
            "runs_dir": str(run),
        }
    )
    data = stage_yolo(dataset, run / "dataset-view", config["slug"])
    weights = fetch(config["architecture"] + ".pt", resolve_path(config["pretrained_root"]))
    batch = config["batch"]
    while True:
        try:
            model = YOLO(str(resume or weights))
            if resume:
                model.train(resume=True, device=device, batch=batch)
            else:
                model.train(
                    data=str(data),
                    epochs=config["epochs"],
                    patience=config["patience"],
                    imgsz=config["image_size"],
                    batch=batch,
                    nbs=config["effective_batch"],
                    device=device,
                    workers=config["workers"],
                    seed=config["seed"],
                    deterministic=True,
                    optimizer="AdamW",
                    lr0=config["lr"],
                    weight_decay=config["weight_decay"],
                    project=str(run),
                    name="fit",
                    exist_ok=True,
                    pretrained=True,
                    amp=False,
                    plots=False,
                    cache=False,
                    save=True,
                    val=True,
                    mosaic=0.2 if config["slug"] == "cigarette_smoking" else 0.5,
                    close_mosaic=min(10, config["epochs"]),
                    mixup=0.0,
                    flipud=0.0,
                    fliplr=0.5,
                    scale=0.2,
                    translate=0.1,
                    hsv_h=0.01,
                    hsv_s=0.2,
                    hsv_v=0.2,
                )
            best = Path(model.trainer.best)
            config["effective_batch_size"] = batch
            return best, YOLO(str(best))
        except torch.cuda.OutOfMemoryError:
            if batch == 1:
                raise RuntimeError("GPU memory exhausted at batch 1; use device: cpu or a larger GPU")
            last = run / "fit/weights/last.pt"
            resume = last if last.exists() else resume
            batch = max(1, batch // 2)
            torch.cuda.empty_cache()
            seed_everything(config["seed"])
            LOG.warning("GPU memory limit: restarting with batch %s; resolution and effective batch unchanged", batch)


def make_encoder(config: dict) -> tuple[nn.Module, int]:
    import torchvision.models as models

    if config["architecture"] == "mobilenet_v3_small":
        model = models.mobilenet_v3_small(weights=None)
        model.load_state_dict(
            torch.load(
                fetch("mobilenet_v3_small-047dcff4.pth", resolve_path(config["pretrained_root"])),
                map_location="cpu",
                weights_only=True,
            )
        )
        return nn.Sequential(model.features, model.avgpool), 576
    if config["architecture"] == "resnet18":
        model = models.resnet18(weights=None)
        model.load_state_dict(
            torch.load(
                fetch("resnet18-f37072fd.pth", resolve_path(config["pretrained_root"])),
                map_location="cpu",
                weights_only=True,
            )
        )
        return nn.Sequential(*list(model.children())[:-1]), 512
    raise ValueError("Entrance encoder must be mobilenet_v3_small or resnet18")


def classifier_data(config: dict, dataset: Path, run: Path, network: nn.Module, device: str) -> dict[str, Dataset]:
    """Extract frozen representations; dataset files remain unmodified."""
    slug = config["slug"]
    directory, cached = feature_cache(config, dataset, network, run)
    if cached is not None:
        write_json(run / "pose_failures.json", {"count": 0, "failures": [], "cached": True})
        return cached
    data = {split: FeatureWriter(directory, split) for split in ("train", "val", "test")}
    pose = None
    pose_failures = []
    if slug == "body_state" and not config.get("smoke"):
        pose = PoseExtractor(fetch("pose_landmarker_lite.task", resolve_path(config["pretrained_root"])))
    try:
        for record in jsonl(dataset / "manifest.jsonl"):
            annotation = json.loads((dataset / record["annotation"]).read_text())
            if slug == "body_state":
                rgb = np.asarray(Image.open(dataset / record["path"]).convert("RGB"))
                detected = pose.extract(rgb) if pose else []
                for person in annotation["people"]:
                    if config.get("smoke"):
                        points = person["landmarks"]
                    else:
                        from safesight.inference.engine import iou

                        match = max(detected, key=lambda p: iou(p.box, person["box"]), default=None)
                        if match is None or iou(match.box, person["box"]) < 0.1:
                            pose_failures.append(
                                {
                                    "sample_id": record["sample_id"],
                                    "path": record["path"],
                                    "box": person["box"],
                                    "reason": "No reliable pose association; inspect visibility/annotations",
                                }
                            )
                            continue
                        points = match.keypoints
                    data[record["split"]].append(
                        (
                            torch.tensor(points, dtype=torch.float32),
                            torch.tensor(CLASSES[slug].index(person["label"])),
                            torch.tensor(1),
                        )
                    )
            else:
                images = []
                for _, rgb in frames(dataset / record["path"], config["sequence_fps"]):
                    images.append(entrance_frame(rgb, config["image_size"], annotation.get("roi")))
                    if len(images) >= config["sequence_length"]:
                        break
                if not images:
                    raise ValueError("Sequence has no frames")
                length = len(images)
                if record["split"] == "train" and not config.get("smoke"):
                    # One transformation is shared across the complete clip.
                    brightness = float(np.random.uniform(0.9, 1.1))
                    flip = bool(np.random.random() < 0.5)
                    images = [
                        np.clip((image[:, ::-1] if flip else image).astype(np.float32) * brightness, 0, 255).astype(
                            np.uint8
                        )
                        for image in images
                    ]
                tensor = torch.from_numpy(np.stack(images).transpose(0, 3, 1, 2).astype(np.float32) / 255)
                network.eval()
                features = []
                with torch.inference_mode():
                    for chunk in tensor.split(max(1, config["batch"])):
                        features.append(network.encode(chunk.to(device)).cpu())
                features = torch.cat(features)
                features = torch.cat([features, torch.zeros(config["sequence_length"] - length, features.shape[1])])
                data[record["split"]].append(
                    (features, torch.tensor(CLASSES[slug].index(annotation["label"])), torch.tensor(length))
                )
    finally:
        if pose:
            pose.close()
    write_json(run / "pose_failures.json", {"failures": pose_failures, "count": len(pose_failures)})
    if pose_failures:
        raise ValueError(f"{len(pose_failures)} pose examples failed; see {run / 'pose_failures.json'}")
    index = {split: writer.rows for split, writer in data.items()}
    write_json(directory / "index.json", index)
    result = {split: FeatureDataset(directory, rows) for split, rows in index.items()}
    return result


def classification_metrics(model: nn.Module, data: Dataset, slug: str, device: str, batch_size: int = 8) -> dict:
    model.eval()
    predictions, truth = [], []
    with torch.inference_mode():
        for features, labels, lengths in DataLoader(data, batch_size=batch_size):
            scores = (
                model(features.to(device))
                if slug == "body_state"
                else model.classify(features.to(device), lengths.to(device))
            )
            predictions.extend(scores.argmax(-1).cpu().tolist())
            truth.extend(labels.tolist())
    report = classification_report(
        truth,
        predictions,
        labels=list(range(len(CLASSES[slug]))),
        target_names=CLASSES[slug],
        output_dict=True,
        zero_division=0,
    )
    return {
        "macro_f1": f1_score(
            truth, predictions, labels=list(range(len(CLASSES[slug]))), average="macro", zero_division=0
        ),
        "per_class": {name: report[name] for name in CLASSES[slug]},
        "confusion_matrix": confusion_matrix(truth, predictions, labels=list(range(len(CLASSES[slug])))).tolist(),
    }


def fit_classifier(
    config: dict, dataset: Path, run: Path, device: str, resume: Path | None
) -> tuple[Path, nn.Module, dict]:
    slug = config["slug"]
    network = (
        BodyMLP(len(CLASSES[slug]), config["hidden_sizes"], config["dropout"])
        if slug == "body_state"
        else EntranceLSTM(*make_encoder(config), len(CLASSES[slug]), config["dropout"])
    )
    network.to(device)
    before_features = (random.getstate(), np.random.get_state(), torch.get_rng_state())
    data = classifier_data(config, dataset, run, network, device)
    random.setstate(before_features[0])
    np.random.set_state(before_features[1])
    torch.set_rng_state(before_features[2])
    if slug == "body_state":
        with torch.no_grad():
            total, square, count = None, None, 0
            for points, _, _ in DataLoader(data["train"], batch_size=config["batch"]):
                features = network.features(points.to(device))
                total = features.sum(0) if total is None else total + features.sum(0)
                square = features.square().sum(0) if square is None else square + features.square().sum(0)
                count += len(features)
            mean = total / count
            network.mean.copy_(mean)
            network.scale.copy_(
                ((square - count * mean.square()) / max(1, count - 1)).clamp(min=0).sqrt().clamp(min=0.05)
            )
    frequencies = torch.bincount(data["train"].labels, minlength=len(CLASSES[slug])).float()
    weights = frequencies.sum() / (len(frequencies) * frequencies.clamp(min=1))
    criterion = nn.CrossEntropyLoss(weight=weights.to(device), reduction="none")
    optimizer = torch.optim.AdamW(
        [p for p in network.parameters() if p.requires_grad], lr=config["lr"], weight_decay=config["weight_decay"]
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=config["epochs"])
    start, best, stale = 0, -1.0, 0
    best_state = copy.deepcopy(network.state_dict())
    if resume:
        checkpoint = torch.load(resume, map_location=device, weights_only=False)
        restore_state(network, optimizer, scheduler, checkpoint)
        start, best, stale = checkpoint["epoch"], checkpoint["best"], checkpoint["stale"]
        best_state = checkpoint["best_state"]
    batch = checkpoint.get("batch", config["batch"]) if resume else config["batch"]
    epoch = start
    while epoch < config["epochs"]:
        save_checkpoint(
            run / "epoch-start.pt",
            {
                "model": network.state_dict(),
                "optimizer": optimizer.state_dict(),
                "scheduler": scheduler.state_dict(),
                "python_rng": random.getstate(),
                "numpy_rng": np.random.get_state(),
                "torch_rng": torch.get_rng_state(),
                "cuda_rng": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None,
            },
        )
        try:
            network.train()
            if slug == "entrance_guard":
                network.encoder.eval()
            loader = DataLoader(data["train"], batch_size=batch, shuffle=True, num_workers=0)
            optimizer.zero_grad()
            total = 0.0
            accumulation = max(1, math.ceil(config["effective_batch"] / batch))
            for index, (features, labels, lengths) in enumerate(loader):
                features, labels, lengths = features.to(device), labels.to(device), lengths.to(device)
                if slug == "body_state":
                    features = features.clone()
                    features[:, :, :3] += torch.randn_like(features[:, :, :3]) * 0.005
                    mask = torch.rand_like(features[:, :, 3]) < 0.03
                    features[:, :, 3][mask] = 0
                scores = network(features) if slug == "body_state" else network.classify(features, lengths)
                loss = criterion(scores, labels).mean()
                if not torch.isfinite(loss):
                    raise ValueError("Non-finite training loss; inspect labels and features")
                (loss * accumulation_weight(index, len(loader), batch, len(data["train"]), accumulation)).backward()
                total += loss.item()
                if (index + 1) % accumulation == 0 or index + 1 == len(loader):
                    nn.utils.clip_grad_norm_(network.parameters(), 1.0)
                    optimizer.step()
                    optimizer.zero_grad()
            scheduler.step()
            metrics = classification_metrics(network, data["val"], slug, device, batch)
            score = metrics["macro_f1"]
            if score > best:
                best, stale, best_state = score, 0, copy.deepcopy(network.state_dict())
            else:
                stale += 1
            epoch += 1
            save_checkpoint(
                run / "last.pt",
                {
                    "model": network.state_dict(),
                    "optimizer": optimizer.state_dict(),
                    "scheduler": scheduler.state_dict(),
                    "epoch": epoch,
                    "batch": batch,
                    "best": best,
                    "stale": stale,
                    "best_state": best_state,
                    "python_rng": random.getstate(),
                    "numpy_rng": np.random.get_state(),
                    "torch_rng": torch.get_rng_state(),
                    "cuda_rng": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None,
                },
            )
            LOG.info("Epoch %d loss %.4f validation macro F1 %.4f", epoch, total / max(1, len(loader)), score)
            with (run / "epochs.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {"epoch": epoch, "batch": batch, "loss": total / max(1, len(loader)), "val_macro_f1": score}
                    )
                    + "\n"
                )
            if stale >= config["patience"]:
                break
        except torch.cuda.OutOfMemoryError:
            if batch == 1:
                raise RuntimeError("Out of GPU memory at batch 1; configure device: cpu")
            rollback = torch.load(run / "epoch-start.pt", map_location="cpu", weights_only=False)
            restore_state(network, optimizer, scheduler, rollback)
            batch = max(1, batch // 2)
            optimizer.zero_grad(set_to_none=True)
            torch.cuda.empty_cache()
            LOG.warning("Reducing batch to %d after GPU memory exhaustion", batch)
    config["effective_batch_size"] = batch
    network.load_state_dict(best_state)
    network.eval()
    artifact = run / "best.ts"
    torch.jit.script(network.cpu()).save(str(artifact))
    network.to(device)
    return artifact, network, data


def main(slug: str) -> int:
    parser = argparse.ArgumentParser(description=f"Train {slug} independently")
    parser.add_argument("--config", default=f"training/{slug}/config.yaml")
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    config = read_yaml(args.config)
    if config["slug"] != slug:
        raise ValueError("Config slug differs from the entrypoint")
    config["smoke"] = args.smoke
    if args.smoke:
        config.update(
            dataset=str(generate(slug)),
            output_root="tests/fixtures/models",
            runs_root="tests/fixtures/runs",
            epochs=1,
            batch=2,
            image_size=128,
            sequence_length=10,
            architecture="yolo11n" if slug in YOLO_SLUGS else config["architecture"],
        )
    seed_everything(config["seed"])
    from training.common.splitting import materialize_splits

    dataset = materialize_splits(
        resolve_path(config["dataset"]),
        slug,
        config["seed"],
        tuple(config.get("split_ratios", [0.7, 0.15, 0.15])),
    )
    result = validate(dataset, slug, args.smoke, qualification=False)
    result.write(ROOT / "artifacts/reports/validation" / slug)
    if not result.valid:
        raise ValueError("Dataset invalid:\n" + "\n".join(result.errors))
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    resume = resolve_path(args.resume) if args.resume else None
    run = (
        resume.parent.parent
        if resume and slug in YOLO_SLUGS
        else resume.parent
        if resume
        else resolve_path(config["runs_root"]) / slug / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    )
    if resume and slug in YOLO_SLUGS and run.name == "fit":
        run = run.parent
    run.mkdir(parents=True, exist_ok=True)
    metadata = {"dataset_hash": result.dataset_hash, "config_hash": config_hash, "config": config}
    if resume:
        existing = json.loads((run / "run.json").read_text())
        if existing["dataset_hash"] != result.dataset_hash or existing["config_hash"] != config_hash:
            raise ValueError("Resume rejected: dataset/config/architecture changed")
        if (run / "report.json").exists():
            print(f"Completed run already evaluated; reusing {run / 'report.json'}")
            return 0
    write_json(run / "run.json", metadata)
    write_json(run / "dataset_inventory.json", dataset_inventory(dataset, slug))
    logging.basicConfig(
        level=logging.INFO,
        handlers=[logging.StreamHandler(), logging.FileHandler(run / "train.log", encoding="utf-8")],
        force=True,
    )
    device = select_device(config["device"])
    if slug in YOLO_SLUGS:
        artifact, model = fit_yolo(config, dataset, run, device, resume)
        data = None
    else:
        artifact, model, data = fit_classifier(config, dataset, run, device, resume)
    model_root = resolve_path(config["output_root"])
    version = model_root / slug / "versions" / run.name
    version.mkdir(parents=True, exist_ok=True)
    target = version / artifact.name
    shutil.copyfile(artifact, target)
    pose_asset = fetch("pose_landmarker_lite.task", resolve_path(config["pretrained_root"]))
    (model_root / "_pretrained").mkdir(parents=True, exist_ok=True)
    if pose_asset.resolve() != (model_root / "_pretrained" / pose_asset.name).resolve():
        shutil.copyfile(pose_asset, model_root / "_pretrained" / pose_asset.name)
    card = {
        "schema_version": 1,
        "slug": slug,
        "loader": "ultralytics" if slug in YOLO_SLUGS else "torchscript",
        "architecture": config["architecture"],
        "classes": CLASSES[slug],
        "artifact": target.relative_to(model_root).as_posix(),
        "sha256": sha256(target),
        "run_id": run.name,
        "input_size": config["image_size"],
        "sequence_length": config["sequence_length"],
        "sequence_fps": config["sequence_fps"],
        "preprocessing": "v1",
        "thresholds": {},
        "quality": {"status": "FAIL", "reasons": ["Evaluation in progress"]},
        "synthetic": args.smoke,
        "dataset_hash": result.dataset_hash,
        "config_hash": config_hash,
        "date": datetime.now(timezone.utc).isoformat(),
        "seed": config["seed"],
        "library_versions": {
            name: importlib.metadata.version(name)
            for name in ("torch", "torchvision", "ultralytics", "mediapipe", "numpy")
        },
        "temporal_policy": read_yaml(config["inference_config"]),
    }
    card["source_identity"] = source_identity()
    card["context_asset_sha256"] = sha256(pose_asset)
    write_json(version / "model_card.json", card)
    write_json(version / "training_config.json", config)
    if slug in YOLO_SLUGS:
        measured = model.val(
            data=str(run / "dataset-view/data.yaml"),
            split="val",
            imgsz=config["image_size"],
            device=device,
            plots=False,
            verbose=False,
        )
        validation_metrics = {
            "map50_95": float(measured.box.map),
            "ap50": {CLASSES[slug][int(i)]: float(ap) for i, ap in zip(measured.box.ap_class_index, measured.box.ap50)},
        }
    else:
        validation_metrics = classification_metrics(
            model, data["val"], slug, device, config.get("effective_batch_size", config["batch"])
        )
    card.update(
        quality={"status": "FAIL", "reasons": ["Training complete; alert qualification has not been performed"]},
        metrics={"validation": validation_metrics},
        training_dataset_hash=result.dataset_hash,
    )
    write_json(version / "model_card.json", card)
    report = {
        "stage": "training",
        "quality": card["quality"],
        "validation": validation_metrics,
        "dataset_hash": result.dataset_hash,
        "synthetic": args.smoke,
    }
    write_json(run / "report.json", report)
    write_json(version / "report.json", report)
    write_json(version / "training_report.json", report)
    text = (
        f"# {slug} training report\n\nEvaluation only: qualification required.\n\n```json\n"
        + json.dumps(report, indent=2)
        + "\n```\n"
    )
    (version / "report.md").write_text(text, encoding="utf-8")
    print(f"Training complete: {version}; model remains evaluation-only")
    return 0


def qualify_version(slug: str, version: Path, dataset: Path, config: dict) -> int:
    """Evaluate a frozen version without fitting or changing its weights."""
    card = json.loads((version / "model_card.json").read_text())
    model_root = version.parents[2]
    run = version / "qualification"
    run.mkdir(exist_ok=True)
    previous = run / "report.json"
    if previous.exists():
        print("Reusing completed qualification; test data is not replayed")
        return 0 if json.loads(previous.read_text())["quality"]["status"] == "PASS" else 2
    training = validate(dataset, slug, card["synthetic"], qualification=False)
    if training.dataset_hash != card.get("training_dataset_hash", card["dataset_hash"]):
        raise ValueError("Training samples differ from the frozen model; qualification rejected")
    result = validate(dataset, slug, card["synthetic"], qualification=True)
    result.write(run)
    if not result.valid:
        raise ValueError("Qualification dataset invalid: " + "; ".join(result.errors))
    device = select_device(config["device"])
    registry = Registry(
        model_root,
        evaluation=True,
        device=device,
        selected={slug: (version / "model_card.json").relative_to(model_root).as_posix()},
    )
    try:
        if slug not in registry.adapters:
            raise RuntimeError(registry.status[slug])
        adapter = registry.adapters[slug]
        model = adapter.model
        data = classifier_data(config, dataset, run, model, device) if slug not in YOLO_SLUGS else None
        if slug in YOLO_SLUGS:
            stage_yolo(dataset, run / "dataset-view", slug)
        inference_config = card["temporal_policy"]
        val_cache = cache_predictions(registry, slug, dataset, "val")
        thresholds, curves = calibrate(
            val_cache, slug, inference_config, config["quality"]["precision"], config["quality"]
        )
        # Every choice is frozen before the held-out test is touched for evaluation.
        card["thresholds"] = thresholds
        validation_metrics = replay(val_cache, slug, inference_config, thresholds)
        write_json(run / "calibration.json", {"thresholds": thresholds, "curves": curves})
        if slug in YOLO_SLUGS:
            measured = model.val(
                data=str(run / "dataset-view/data.yaml"),
                split="test",
                imgsz=config["image_size"],
                batch=config["batch"],
                device=device,
                plots=True,
                project=str(run),
                name="test",
                verbose=False,
            )
            model_metrics = {
                "map50_95": float(measured.box.map),
                "ap50": {
                    CLASSES[slug][int(index)]: float(ap)
                    for index, ap in zip(measured.box.ap_class_index, measured.box.ap50)
                },
                "confusion_matrix": measured.confusion_matrix.matrix.tolist(),
            }
            model_metrics["by_object_size"] = evaluate_sizes(
                model, dataset, CLASSES[slug], config["image_size"], device
            )
        else:
            model_metrics = classification_metrics(
                model, data["test"], slug, device, config.get("effective_batch_size", config["batch"])
            )
        test_cache = cache_predictions(registry, slug, dataset, "test")
        event_metrics = replay(test_cache, slug, inference_config, thresholds)
        model_metrics["evaluation_scope"] = "frozen_model_test_split"
        event_metrics["evaluation_scope"] = "deployed_preprocessing_fusion_and_temporal_pipeline"
        quality = quality_gate(config, result, model_metrics, event_metrics, thresholds, validation_metrics)
        card.update(
            qualification_dataset_hash=result.dataset_hash,
            quality=quality,
            metrics={"model": model_metrics, "events": event_metrics},
        )
        write_json(version / "model_card.json", card)
        report = {
            "slug": slug,
            "synthetic": card["synthetic"],
            "quality": quality,
            "model": model_metrics,
            "events": event_metrics,
            "validation_events": validation_metrics,
            "thresholds": thresholds,
            "validation_curves": curves,
            "device": device,
            "dataset_hash": result.dataset_hash,
        }
        failure_gallery(dataset, run / "failures", event_metrics.get("failure_examples", []))
        write_json(run / "report.json", report)
        write_json(version / "report.json", report)
        lines = (
            [
                f"# {slug} training report",
                f"\nQuality: **{quality['status']}**",
                f"\nSynthetic: {card['synthetic']}; device: {device}",
                "\n## Diagnosis",
            ]
            + [f"- {r}" for r in quality["reasons"]]
            + ["\n## Measured results", "```json", json.dumps(report, indent=2), "```"]
        )
        (run / "report.md").write_text("\n".join(lines), encoding="utf-8")
        shutil.copyfile(run / "report.md", version / "report.md")
        if quality["status"] == "PASS" and not card["synthetic"]:
            write_json(model_root / slug / "model_card.json", card)
        print(f"{slug}: software execution completed; quality {quality['status']}; report {run / 'report.md'}")
        for reason in quality["reasons"]:
            print(f"  {reason}")
        return 0 if card["synthetic"] or quality["status"] == "PASS" else 2
    finally:
        registry.close()


def cli(slug: str) -> None:
    """Print actionable failures while keeping quality failures a distinct exit code."""
    try:
        raise SystemExit(main(slug))
    except (ValueError, OSError, RuntimeError) as error:
        LOG.exception("Training failed: %s", error)
        raise SystemExit(1)
