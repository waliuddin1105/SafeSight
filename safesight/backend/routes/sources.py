"""Location/source configuration and live capture endpoints."""

from __future__ import annotations

import io
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from flask import abort, jsonify, request
from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, select

from safesight.config import within
from safesight.contracts import SLUGS
from safesight.storage.schema import (
    FramePacket,
    Location,
    Source,
    utcnow,
)


from safesight.backend.context import cfg, sessions, media
from safesight.backend.serializers import serialize

from flask import Blueprint
from safesight.backend.security import authenticated, admin
from safesight.backend.validation import payload, valid_identifier, record

bp = Blueprint("sources", __name__)


@bp.route("/api/v1/locations", methods=["GET", "POST"])
@authenticated
def locations():
    with sessions.begin() as db:
        if request.method == "POST":
            admin()
            data = payload()
            name = str(data.get("name", "")).strip()
            if not name or len(name) > 120:
                abort(400, "Location name must contain 1–120 characters")
            timezone_name = data.get("timezone", cfg["timezone"])
            try:
                ZoneInfo(timezone_name)
            except (KeyError, TypeError):
                abort(400, "Unknown timezone")
            policies = data.get("policies", {})
            if not isinstance(policies, dict) or any(k != "body_state" for k in policies):
                abort(400, "Location policies must be an object containing optional body_state rules")
            if "body_state" in policies:
                from safesight.config import read_yaml
                from safesight.contracts.configuration import TemporalRule

                base = read_yaml(cfg["inference_config"])["body_state"]
                if not isinstance(policies["body_state"], dict):
                    abort(400, "body_state policy must be an object")
                TemporalRule.model_validate({**base, **policies["body_state"]})
            location = Location(name=name, timezone=timezone_name, policies=policies)
            db.add(location)
            db.flush()
            return jsonify(serialize(location)), 201
        return jsonify(items=[serialize(row) for row in db.scalars(select(Location).order_by(Location.name))])


@bp.route("/api/v1/sources", methods=["GET", "POST"])
@authenticated
def sources():
    with sessions.begin() as db:
        if request.method == "POST":
            admin()
            data = payload()
            record(db, Location, data.get("location_id"))
            kind = data.get("kind", "browser")
            if kind not in ("browser", "usb", "rtsp", "upload"):
                abort(400, "Invalid source kind")
            models = data.get("enabled_models", list(SLUGS))
            if not isinstance(models, list) or not models or any(name not in SLUGS for name in models):
                abort(400, "Choose supported models")
            source_config = data.get("config", {})
            if not isinstance(source_config, dict):
                abort(400, "Source configuration must be an object")
            for region in ("entrance_roi", "guard_region"):
                box = source_config.get(region, [0, 0, 1, 1])
                if (
                    not isinstance(box, list)
                    or len(box) != 4
                    or not all(isinstance(v, (int, float)) for v in box)
                    or not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1)
                ):
                    abort(400, f"{region} must be a normalized xyxy box")
            line = source_config.get("crossing_line_y", 0.75)
            if not isinstance(line, (int, float)) or not 0 < line < 1:
                abort(400, "crossing_line_y must be between zero and one")
            if kind == "rtsp":
                url = urlparse(source_config.get("uri", ""))
                if url.scheme != "rtsp" or url.hostname not in cfg["allowed_rtsp_hosts"]:
                    abort(400, "RTSP host must be explicitly allowed in application configuration")
            if kind == "usb" and (
                not isinstance(source_config.get("device", 0), int) or source_config.get("device", 0) < 0
            ):
                abort(400, "USB device must be a nonnegative index")
            name = str(data.get("name", "")).strip()
            if not name or len(name) > 120:
                abort(400, "Source name must contain 1–120 characters")
            source = Source(
                name=name, location_id=data["location_id"], kind=kind, config=source_config, enabled_models=models
            )
            db.add(source)
            db.flush()
            return jsonify(serialize(source)), 201
        return jsonify(items=[serialize(row) for row in db.scalars(select(Source).order_by(Source.name))])


@bp.post("/api/v1/sources/<source_id>/start")
@authenticated
def start_source(source_id):
    with sessions.begin() as db:
        # Serializes the capacity decision across all source starts.
        db.execute(select(Location).with_for_update()).all()
        source = record(db, Source, source_id)
        if source.kind == "upload":
            abort(400, "Upload sources are started by submitting recordings")
        active = db.scalar(
            select(func.count()).select_from(Source).where(Source.active.is_(True), Source.id != source.id)
        )
        if active >= cfg["max_live_sources"]:
            abort(409, "Another live source is active; stop it first")
        source.active, source.last_sequence, source.last_capture_ms = True, -1, -1
        for packet in db.scalars(select(FramePacket).where(FramePacket.source_id == source.id)):
            within(media, packet.path).unlink(missing_ok=True)
            db.delete(packet)
        source.generation += 1
        source.health = {"status": "waiting", "dropped_frames": 0}
        source.last_frame_at = utcnow()
        return jsonify(serialize(source))


@bp.post("/api/v1/sources/<source_id>/stop")
@authenticated
def stop_source(source_id):
    with sessions.begin() as db:
        source = record(db, Source, source_id)
        source.active = False
        source.health = {**source.health, "status": "stopped"}
        return jsonify(serialize(source))


@bp.post("/api/v1/sources/<source_id>/frames")
@authenticated
def ingest_frame(source_id):
    valid_identifier(source_id)
    if request.content_type != "image/jpeg" or (request.content_length or 0) > cfg["max_frame_bytes"]:
        abort(413, "Frame must be JPEG within the configured size limit")
    raw = request.stream.read(cfg["max_frame_bytes"] + 1)
    if len(raw) > cfg["max_frame_bytes"]:
        abort(413, "Frame exceeds size limit")
    try:
        sequence = int(request.headers["X-Sequence"])
        timestamp = float(request.headers["X-Capture-Ms"])
        if sequence < 0 or not 0 <= timestamp < 1e15:
            raise ValueError()
        with Image.open(io.BytesIO(raw)) as image:
            if image.format != "JPEG" or image.width * image.height > cfg["max_frame_pixels"]:
                raise ValueError()
            image.verify()
    except (ValueError, KeyError, UnidentifiedImageError, OSError):
        abort(400, "Invalid frame, sequence, or capture timestamp")
    with sessions.begin() as db:
        source = db.scalar(select(Source).where(Source.id == source_id).with_for_update())
        if source is None:
            abort(404)
        if not source.active or source.kind != "browser":
            abort(409, "Browser source is not active")
        if sequence <= source.last_sequence or timestamp <= source.last_capture_ms:
            abort(409, "Duplicate or out-of-order frame")
        origin = source.health.get("capture_origin_ms", timestamp)
        elapsed = (timestamp - origin) / 1000
        packets = list(
            db.scalars(select(FramePacket).where(FramePacket.source_id == source_id).order_by(FramePacket.sequence))
        )
        expired = [
            p
            for p in packets
            if p.generation != source.generation or elapsed - p.timestamp > cfg["pending_frame_seconds"]
        ]
        for packet in expired:
            within(media, packet.path).unlink(missing_ok=True)
            db.delete(packet)
        remaining = len(packets) - len(expired)
        if remaining >= int(cfg["sample_fps"] * cfg["pending_frame_seconds"]):
            abort(429, "Frame queue full; reduce capture rate")
        relative = f"spool/{source_id}/{source.generation}_{sequence}.jpg"
        path = within(media, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.with_suffix(".tmp").write_bytes(raw)
        path.with_suffix(".tmp").replace(path)
        db.add(
            FramePacket(
                source_id=source_id,
                generation=source.generation,
                sequence=sequence,
                timestamp=elapsed,
                path=relative,
            )
        )
        source.last_sequence, source.last_capture_ms, source.last_frame_at = sequence, timestamp, utcnow()
        source.health = {
            **source.health,
            "status": "receiving",
            "capture_origin_ms": origin,
            "dropped_frames": source.health.get("dropped_frames", 0) + len(expired),
            "queue_depth": remaining + 1,
        }
        return jsonify(accepted=True, queue_depth=remaining + 1), 202
