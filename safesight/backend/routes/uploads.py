"""Recording upload and processing-job endpoints."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import av
import json
import hashlib
import shutil
from sqlalchemy import select, func
from flask import send_file
from safesight.backend.context import cfg
from safesight.inference.snapshots import snapshot_models
from safesight.storage.schema import JobFrame
from flask import abort, jsonify, request

from safesight.config import within
from safesight.storage.schema import (
    Job,
    Source,
    identifier,
)


from safesight.backend.context import sessions, media
from safesight.backend.serializers import serialize

from flask import Blueprint
from safesight.backend.security import authenticated
from safesight.backend.validation import record

bp = Blueprint("uploads", __name__)


@bp.post("/api/v1/uploads")
@authenticated
def upload():
    file = request.files.get("file")
    if not file or Path(file.filename or "").suffix.lower() not in (".mp4", ".mov", ".mkv", ".avi"):
        abort(400, "Upload a supported video recording")
    with sessions() as db:
        source = record(db, Source, request.form.get("source_id"))
        if source.kind != "upload":
            abort(400, "Choose an upload source")
        source_id = source.id
        selected = json.loads(request.form.get("models", json.dumps(source.enabled_models)))
        if not isinstance(selected, list):
            abort(400, "models must be a list")
        snapshot = snapshot_models(
            cfg, selected, request.form.get("evaluation") == "true", json.loads(request.form.get("versions", "{}"))
        )
        snapshot["source_config"] = {
            k: v for k, v in source.config.items() if k in ("entrance_roi", "guard_region", "crossing_line_y")
        }
        from safesight.storage.schema import Location

        location = db.get(Location, source.location_id)
        snapshot["source_config"]["location_policies"] = dict(location.policies) if location else {}
        snapshot.pop("fingerprint")
        snapshot["fingerprint"] = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    if shutil.disk_usage(str(media)).free < cfg["minimum_free_bytes"] + (
        request.content_length or cfg["max_upload_bytes"]
    ):
        abort(507, "Insufficient media storage")
    relative = f"uploads/{identifier()}{Path(file.filename).suffix.lower()}"
    path = within(media, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        file.save(path)
        with av.open(str(path), timeout=cfg["decode_timeout_seconds"]) as container:
            stream = container.streams.video[0]
            next(container.decode(stream))
            duration = (
                float(stream.duration * stream.time_base)
                if stream.duration
                else float(container.duration or 0) / av.time_base
            )
        captured = request.form.get("captured_at")
        captured_at = datetime.fromisoformat(captured.replace("Z", "+00:00")) if captured else None
        if captured_at and captured_at.tzinfo is None:
            raise ValueError("Capture time must include timezone")
        truth = request.form.get("ground_truth", "").strip()
        if truth:
            from safesight.contracts import SLUGS
            from training.common.datasets import alert_classes, valid_box
            import math

            annotations = json.loads(truth)
            if not isinstance(annotations, dict) or not isinstance(annotations.get("events"), list) or duration <= 0:
                raise ValueError("Ground truth requires events and known video duration")
            for event in annotations["events"]:
                if not isinstance(event, dict):
                    raise ValueError("Each ground truth event must be an object")
                slug = event.get("slug")
                if slug not in SLUGS or slug not in selected or event.get("subtype") not in alert_classes(slug):
                    raise ValueError("Ground truth category does not match selected models")
                if (
                    not all(
                        isinstance(event.get(k), (int, float)) and math.isfinite(event[k]) for k in ("start", "end")
                    )
                    or not 0 <= event["start"] < event["end"] <= duration + 0.1
                    or not valid_box(event.get("box", []))
                ):
                    raise ValueError("Invalid ground truth timing or actor box")
            snapshot["ground_truth"] = annotations
        with sessions.begin() as db:
            job = Job(source_id=source_id, path=relative, duration=duration, captured_at=captured_at, snapshot=snapshot)
            db.add(job)
            db.flush()
            result = serialize(job)
        return jsonify(result), 202
    except (av.error.FFmpegError, IndexError, StopIteration, ValueError):
        path.unlink(missing_ok=True)
        abort(400, "Invalid recording or capture time")
    except Exception:
        path.unlink(missing_ok=True)
        raise


@bp.get("/api/v1/jobs/<job_id>")
@authenticated
def job_detail(job_id):
    with sessions() as db:
        return jsonify(serialize(record(db, Job, job_id)))


@bp.get("/api/v1/jobs")
@authenticated
def jobs():
    page = max(1, int(request.args.get("page", 1)))
    with sessions() as db:
        rows = db.scalars(select(Job).order_by(Job.created_at.desc(), Job.id).offset((page - 1) * 25).limit(25))
        total = db.scalar(select(func.count()).select_from(Job))
        return jsonify(items=[serialize(row) for row in rows], total=total, page=page)


@bp.post("/api/v1/jobs/<job_id>/cancel")
@authenticated
def cancel_job(job_id):
    with sessions.begin() as db:
        job = record(db, Job, job_id)
        if job.state not in ("completed", "failed", "cancelled"):
            job.cancel_requested = True
            if job.state in ("queued", "paused"):
                job.state = "cancelled"
        return jsonify(serialize(job))


@bp.get("/api/v1/jobs/<job_id>/video")
@authenticated
def job_video(job_id):
    with sessions() as db:
        job = record(db, Job, job_id)
        return send_file(within(media, job.path), conditional=True)


@bp.get("/api/v1/jobs/<job_id>/predictions")
@authenticated
def job_predictions(job_id):
    after = float(request.args.get("after", -1))
    with sessions() as db:
        record(db, Job, job_id)
        rows = list(
            db.scalars(
                select(JobFrame)
                .where(JobFrame.job_id == job_id, JobFrame.timestamp > after)
                .order_by(JobFrame.timestamp)
                .limit(250)
            )
        )
        return jsonify(items=[serialize(row) for row in rows], next_after=rows[-1].timestamp if rows else None)


@bp.get("/api/v1/jobs/<job_id>/incidents")
@authenticated
def job_incidents(job_id):
    from safesight.storage.schema import Incident

    with sessions() as db:
        record(db, Job, job_id)
        rows = db.scalars(select(Incident).where(Incident.event_key.startswith(job_id)).order_by(Incident.start_offset))
        return jsonify(items=[serialize(row) for row in rows])


@bp.get("/api/v1/jobs/<job_id>/metrics")
@authenticated
def job_metrics(job_id):
    from safesight.storage.schema import Incident
    from safesight.inference.engine import iou

    with sessions() as db:
        job = record(db, Job, job_id)
        truth = job.snapshot.get("ground_truth")
        if truth is None or job.state != "completed":
            return jsonify(available=False, reason="Compatible ground truth and a completed job are required")
        predictions = list(db.scalars(select(Incident).where(Incident.event_key.startswith(job_id))))
        used = set()
        for prediction in predictions:
            matches = []
            for index, event in enumerate(truth["events"]):
                overlap = min(prediction.end_offset, event["end"]) - max(prediction.start_offset, event["start"])
                box = prediction.details.get("box")
                if (
                    index not in used
                    and prediction.slug == event["slug"]
                    and prediction.subtype == event["subtype"]
                    and overlap > 0
                    and box
                    and iou(box, event["box"]) >= 0.1
                ):
                    matches.append((overlap, index))
            if matches:
                used.add(max(matches)[1])
        tp, fp, fn = len(used), len(predictions) - len(used), len(truth["events"]) - len(used)
        return jsonify(
            available=True,
            true_positive=tp,
            false_positive=fp,
            false_negative=fn,
            precision=tp / (tp + fp) if tp + fp else None,
            recall=tp / (tp + fn) if tp + fn else None,
            note="User-supplied event annotations; testing result only, not production qualification",
        )
