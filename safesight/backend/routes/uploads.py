"""Recording upload and processing-job endpoints."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import av
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
    with sessions.begin() as db:
        source = record(db, Source, request.form.get("source_id"))
        if source.kind != "upload":
            abort(400, "Choose an upload source")
        relative = f"uploads/{identifier()}{Path(file.filename).suffix.lower()}"
        path = within(media, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        file.save(path)
        try:
            with av.open(str(path)) as container:
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
        except (av.error.FFmpegError, IndexError, StopIteration, ValueError) as error:
            path.unlink(missing_ok=True)
            abort(400, f"Invalid recording: {error}")
        job = Job(source_id=source.id, path=relative, duration=duration, captured_at=captured_at)
        db.add(job)
        db.flush()
        return jsonify(serialize(job)), 202


@bp.get("/api/v1/jobs/<job_id>")
@authenticated
def job_detail(job_id):
    with sessions() as db:
        return jsonify(serialize(record(db, Job, job_id)))
