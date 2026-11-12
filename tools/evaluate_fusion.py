"""Calibrate and evaluate the installed smoking/fire combination; never train weights."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from safesight.config import read_yaml, resolve_path, settings, within
from safesight.model_loaders.registry import Registry
from training.common.datasets import jsonl, sha256, video_info, validate_event_record
from training.common.evaluation import cache_predictions, calibrate, replay


def evaluate(config: dict) -> dict:
    """Freeze joint thresholds on validation, then evaluate test exactly once."""
    root = settings()["models_root"]
    slugs = ("cigarette_smoking", "fire_smoke")
    registry = Registry(root, evaluation=True, selected={s: f"{s}/model_card.json" for s in slugs})
    try:
        if set(registry.adapters) != set(slugs):
            raise ValueError(f"Both independent artifacts are required for joint evaluation: {registry.status}")
        dataset = resolve_path(config["dataset"])
        policy = registry.temporal_policy(read_yaml(config["inference_config"]))
        validation_path = resolve_path(config["validation_manifest"])
        test_path = resolve_path(config["test_manifest"])
        val_items, test_items = jsonl(validation_path), jsonl(test_path)
        media_hashes = {}
        for partition, items in (("val", val_items), ("test", test_items)):
            if not items:
                raise ValueError(f"Fusion {partition} manifest is empty")
            for item in items:
                path = within(dataset, item["video"])
                if not item["video"].startswith(f"videos/{partition}/"):
                    raise ValueError("Fusion media path must match its partition")
                duration, _ = video_info(path)
                validate_event_record(item, duration, ["smoking", "fire", "hazardous_smoke", "uncertain_smoke"])
                digest = sha256(path)
                if digest in media_hashes and media_hashes[digest] != partition:
                    raise ValueError("Fusion media content duplicated across partitions")
                media_hashes[digest] = partition
        for field in ("source_id", "group_id", "video"):
            if {r[field] for r in val_items} & {r[field] for r in test_items}:
                raise ValueError(f"Fusion validation/test leakage in {field}")
        # Verify evaluation media are from the independent datasets' held-out groups.
        for slug in slugs:
            manifest = resolve_path(config.get("datasets", {}).get(slug, f"datasets/{slug}")) / "manifest.jsonl"
            if not manifest.exists():
                raise ValueError(f"Provenance manifest required: {manifest}")
            rows = jsonl(manifest)
            training = {r["source_id"] for r in rows if r["split"] == "train"}
            if training & {r["source_id"] for r in val_items + test_items}:
                raise ValueError(f"Fusion footage overlaps {slug} training sources")
            training_groups = {r["group_id"] for r in rows if r["split"] == "train"}
            if training_groups & {r["group_id"] for r in val_items + test_items}:
                raise ValueError(f"Fusion footage overlaps {slug} training scenes/sessions")
        val = cache_predictions(registry, "fire_smoke", dataset, "val", val_items)
        thresholds = {s: dict(registry.adapters[s].card.thresholds) for s in slugs}
        curves = {}
        for slug in slugs:
            for item in val:
                item["companion_thresholds"] = {s: t for s, t in thresholds.items() if s != slug}
            thresholds[slug], curves[slug] = calibrate(
                val, slug, policy, config["quality"]["precision"], config["quality"]
            )
        reasons = []
        validation_metrics = {}
        for slug in slugs:
            for item in val:
                item["companion_thresholds"] = {s: t for s, t in thresholds.items() if s != slug}
            validation_metrics[slug] = replay(val, slug, policy, thresholds[slug])
            for name, row in validation_metrics[slug]["categories"].items():
                if name != "uncertain_smoke" and (
                    row["precision"] is None or row["precision"] < config["quality"]["precision"]
                ):
                    reasons.append(f"Joint validation precision not attained: {slug}/{name}")
        test = cache_predictions(registry, "fire_smoke", dataset, "test", test_items)
        metrics = {}
        for slug in slugs:
            for item in test:
                item["companion_thresholds"] = {s: t for s, t in thresholds.items() if s != slug}
            metrics[slug] = replay(test, slug, policy, thresholds[slug])
            card = registry.adapters[slug].card
            if card.synthetic or card.quality["status"] != "PASS":
                reasons.append(f"{slug} is not production-qualified")
            if metrics[slug]["groups"] < config["quality"]["min_groups"]:
                reasons.append(f"{slug}: insufficient test groups")
            for name, row in metrics[slug]["categories"].items():
                if name == "uncertain_smoke":
                    continue
                if (
                    row["positive"] < config["quality"]["min_positive_events"]
                    or row["negative_videos"] < config["quality"]["min_negative_videos"]
                ):
                    reasons.append(f"{name}: insufficient test support")
                target = config["quality"].get(name + "_recall", 0.9)
                if (
                    row["precision"] is None
                    or row["precision"] < config["quality"]["precision"]
                    or row["recall"] is None
                    or row["recall"] < target
                ):
                    reasons.append(f"{name}: test precision/recall target not met")
        result = {
            "schema_version": 1,
            "status": "FAIL" if reasons else "PASS",
            "reasons": reasons,
            "models": {s: sha256(root / s / "model_card.json") for s in slugs},
            "policy": policy,
            "thresholds": thresholds,
            "validation": validation_metrics,
            "test": metrics,
            "curves": curves,
            "dataset_hashes": {"validation": sha256(validation_path), "test": sha256(test_path)},
        }
        path = root / "fusion_card.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, indent=2, allow_nan=False))
        temporary.replace(path)
        return result
    finally:
        registry.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/fusion.yaml")
    args = parser.parse_args()
    result = evaluate(read_yaml(args.config))
    print(result["status"], *result["reasons"], sep="\n")
    raise SystemExit(0 if result["status"] == "PASS" else 2)
