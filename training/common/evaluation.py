"""Validation-only threshold selection and honest, grouped event evaluation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from safesight.inference.engine import Engine, iou
from safesight.ingestion.video import frames
from safesight.model_loaders.registry import Registry
from training.common.datasets import alert_classes, jsonl, video_info


def cache_predictions(
    registry: Registry, slug: str, dataset: Path, split: str, items: list[dict] | None = None
) -> list[dict]:
    """Run inference once per split; calibration then replays cached predictions."""
    if items is not None:
        items = list(items)
    elif slug == "entrance_guard":
        items = []
        for record in jsonl(dataset / "manifest.jsonl"):
            if record["split"] != split:
                continue
            annotation = json.loads((dataset / record["annotation"]).read_text())
            duration, _ = video_info(dataset / record["path"])
            events = (
                [
                    {
                        "subtype": "unverified_entry",
                        "start": 0,
                        "end": duration,
                        "box": annotation.get("roi", [0, 0, 1, 1]),
                    }
                ]
                if annotation["label"] == "unverified_entry"
                else []
            )
            items.append(
                {
                    "video": record["path"],
                    "events": events,
                    "group_id": record["group_id"],
                    "source_config": {
                        "entrance_roi": annotation.get("roi", [0, 0, 1, 1]),
                        **annotation.get("source_config", {}),
                    },
                }
            )
    else:
        items = jsonl(dataset / "events" / f"{split}.jsonl")
    cached = []
    for item in items:
        for adapter in registry.adapters.values():
            if hasattr(adapter, "buffer"):
                adapter.buffer.clear()
                adapter.source_config = item.get("source_config", {})
        observations = []
        duration = 0.0
        for timestamp, rgb in frames(dataset / item["video"], 5):
            people = registry.pose.extract(rgb) if registry.pose else []
            predictions = [adapter.predict(rgb, timestamp) for adapter in registry.adapters.values()]
            observations.append((timestamp, predictions, people))
            duration = timestamp + 0.2
        cached.append({**item, "observations": observations, "duration": duration})
    return cached


def replay(cached: list[dict], slug: str, config: dict, thresholds: dict[str, float]) -> dict:
    """Evaluate final event behavior; duplicate alerts count as false positives."""
    categories = alert_classes(slug)
    counts = {
        name: {
            "tp": 0,
            "fp": 0,
            "fn": 0,
            "positive": 0,
            "negative_videos": 0,
            "delays": [],
            "hidden_tp": 0,
            "hidden_positive": 0,
        }
        for name in categories
    }
    per_group: dict[str, dict] = {}
    duration = 0.0
    for item in cached:
        engine = Engine(
            config, {slug: thresholds, **item.get("companion_thresholds", {})}, item.get("source_config", {})
        )
        emitted = {}
        first_emitted = {}
        # Replaying must not mutate cached tracker IDs across threshold trials.
        import copy

        for timestamp, prediction, people in item["observations"]:
            predictions = prediction if isinstance(prediction, list) else [prediction]
            for alert in engine.process(copy.deepcopy(predictions), copy.deepcopy(people), timestamp):
                first_emitted.setdefault(alert.event_id, timestamp)
                emitted[alert.event_id] = alert
        group = per_group.setdefault(item["group_id"], {name: {"tp": 0, "fp": 0, "fn": 0} for name in categories})
        duration += item["duration"]
        for name in categories:
            truths = [e for e in item["events"] if e["subtype"] == name]
            predictions = [a for a in emitted.values() if a.candidate.subtype == name]
            used = set()
            matched_hidden = 0
            delays = []
            for alert in predictions:
                matches = [
                    (min(alert.end, truth["end"]) - max(alert.start, truth["start"]), index)
                    for index, truth in enumerate(truths)
                    if index not in used
                    and min(alert.end, truth["end"]) >= max(alert.start, truth["start"])
                    and (
                        not truth.get("box")
                        or not alert.candidate.details.get("box")
                        or iou(truth["box"], alert.candidate.details["box"]) >= 0.1
                    )
                ]
                if matches:
                    index = max(matches)[1]
                    used.add(index)
                    delays.append(max(0.0, first_emitted[alert.event_id] - truths[index]["start"]))
                    matched_hidden += int(truths[index].get("hidden_cigarette", False))
            tp, fp, fn = len(used), len(predictions) - len(used), len(truths) - len(used)
            row = counts[name]
            for key, value in (
                ("tp", tp),
                ("fp", fp),
                ("fn", fn),
                ("positive", len(truths)),
                ("negative_videos", int(not truths)),
                ("hidden_tp", matched_hidden),
                ("hidden_positive", sum(bool(t.get("hidden_cigarette")) for t in truths)),
            ):
                row[key] += value
            row["delays"].extend(delays)
            for key, value in (("tp", tp), ("fp", fp), ("fn", fn)):
                group[name][key] += value
    rng = np.random.default_rng(42)
    for name, row in counts.items():
        row["precision"] = row["tp"] / (row["tp"] + row["fp"]) if row["tp"] + row["fp"] else None
        row["recall"] = row["tp"] / row["positive"] if row["positive"] else None
        row["hidden_recall"] = row["hidden_tp"] / row["hidden_positive"] if row["hidden_positive"] else None
        row["false_alerts_per_hour"] = row["fp"] / (duration / 3600) if duration else None
        row["mean_delay_seconds"] = float(np.mean(row["delays"])) if row["delays"] else None
        rows = [group[name] for group in per_group.values()]
        precision_samples, recall_samples = [], []
        if len(rows) >= 2:
            for _ in range(200):
                sample = [rows[index] for index in rng.integers(0, len(rows), len(rows))]
                tp, fp, fn = (sum(r[key] for r in sample) for key in ("tp", "fp", "fn"))
                if tp + fp:
                    precision_samples.append(tp / (tp + fp))
                if tp + fn:
                    recall_samples.append(tp / (tp + fn))
        row["precision_ci95"] = np.quantile(precision_samples, [0.025, 0.975]).tolist() if precision_samples else None
        row["recall_ci95"] = np.quantile(recall_samples, [0.025, 0.975]).tolist() if recall_samples else None
    return {"categories": counts, "groups": len(per_group), "video_hours": duration / 3600, "per_group": per_group}


def calibrate(
    cached: list[dict], slug: str, config: dict, precision: float, support: dict | None = None
) -> tuple[dict, dict]:
    """Select each alert threshold on validation only; undefined precision is infeasible."""
    curves = {name: [] for name in alert_classes(slug)}
    thresholds = {name: 1.01 for name in curves}
    support = support or {"min_positive_events": 50, "min_negative_videos": 50, "min_groups": 5, "min_predictions": 30}
    for threshold in np.linspace(0.05, 0.95, 19):
        metrics = replay(cached, slug, config, {name: float(threshold) for name in curves})
        for name in curves:
            row = metrics["categories"][name]
            adequate = (
                row["positive"] >= support["min_positive_events"]
                and row["negative_videos"] >= support["min_negative_videos"]
                and metrics["groups"] >= support["min_groups"]
            )
            curves[name].append(
                {
                    "threshold": float(threshold),
                    "precision": row["precision"],
                    "recall": row["recall"],
                    "predicted": row["tp"] + row["fp"],
                    "adequate_support": adequate,
                }
            )
    for name, points in curves.items():
        if name == "uncertain_smoke":
            thresholds[name] = 0.5
            continue
        feasible = [
            p
            for p in points
            if p["adequate_support"]
            and p["precision"] is not None
            and p["precision"] >= precision
            and p["recall"] is not None
            and p["predicted"] >= support.get("min_predictions", 30)
        ]
        if feasible:
            thresholds[name] = max(feasible, key=lambda p: (p["recall"], p["precision"], -p["threshold"]))["threshold"]
    return thresholds, curves


def quality_gate(
    config: dict,
    validation: Any,
    model_metrics: dict,
    event_metrics: dict,
    thresholds: dict,
    validation_metrics: dict | None = None,
) -> dict:
    """Apply explicit measurable targets; missing or synthetic evidence fails visibly."""
    reasons = []
    targets = config["quality"]
    if validation_metrics is None:
        reasons.append("Validation event support was not recorded")
    else:
        if validation_metrics["groups"] < targets["min_groups"]:
            reasons.append("Too few independent validation groups")
        for name, row in validation_metrics["categories"].items():
            if name == "uncertain_smoke":
                continue
            if (
                row["positive"] < targets["min_positive_events"]
                or row["negative_videos"] < targets["min_negative_videos"]
            ):
                reasons.append(f"{name}: insufficient validation support")
            if "hidden_recall" in targets and row["hidden_positive"] < targets.get("min_hidden_events", 50):
                reasons.append("Insufficient hidden-cigarette validation events")
    if validation.synthetic:
        reasons.append("Synthetic execution fixtures cannot establish production quality")
    if validation.leakage:
        reasons.append("Unresolved suspected split leakage requires review")
    if event_metrics["groups"] < targets["min_groups"]:
        reasons.append("Too few independent test groups; collect new sessions")
    if "macro_f1" in targets and model_metrics.get("macro_f1", -1) < targets["macro_f1"]:
        reasons.append("Macro F1 below target; inspect class confusion and minority coverage")
    for label, target in targets.get("ap50", {}).items():
        if model_metrics.get("ap50", {}).get(label, -1) < target:
            reasons.append(f"{label} AP50 below {target}; inspect small objects and annotation quality")
    if (
        "verified_precision" in targets
        and model_metrics.get("per_class", {}).get("verified_entry", {}).get("precision", -1)
        < targets["verified_precision"]
    ):
        reasons.append("Verified-entry precision below target; inspect skipped-step negatives")
    for name, row in event_metrics["categories"].items():
        if name == "uncertain_smoke":
            continue
        if thresholds.get(name, 1.01) > 1:
            reasons.append(f"{name}: no validation threshold attained target precision")
        if row["positive"] < targets["min_positive_events"] or row["negative_videos"] < targets["min_negative_videos"]:
            reasons.append(f"{name}: too few positive/negative evaluation opportunities")
        for metric, target in (("precision", targets["precision"]), ("recall", targets["event_recall"])):
            if row[metric] is None or row[metric] < target:
                reasons.append(f"{name}: {metric} undefined or below {target}")
        if "hidden_recall" in targets and (
            row["hidden_recall"] is None or row["hidden_recall"] < targets["hidden_recall"]
        ):
            reasons.append("Hidden-cigarette recall missing/below target; collect occluded positive examples")
        if "hidden_recall" in targets and row["hidden_positive"] < targets.get("min_hidden_events", 50):
            reasons.append("Insufficient hidden-cigarette test events")
    return {"status": "FAIL" if reasons else "PASS", "reasons": reasons, "targets": targets}
