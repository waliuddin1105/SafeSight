"""Incident filtering, evidence delivery and human review endpoints."""

from __future__ import annotations

from datetime import datetime

from flask import abort, jsonify, request, send_file, session
from sqlalchemy import func, select

from safesight.config import within
from safesight.contracts import SLUGS
from safesight.storage.schema import (
    Evidence,
    Incident,
    IncidentPrediction,
    Review,
)


from safesight.backend.context import sessions, media
from safesight.backend.serializers import serialize

from flask import Blueprint
from safesight.backend.security import authenticated
from safesight.backend.validation import payload, valid_identifier, record

bp = Blueprint("incidents", __name__)


def incident_collection(db, args) -> dict:
    """Return the canonical filtered incident page for standalone and aggregate APIs."""
    if args.get("location"):
        valid_identifier(args["location"])
    if args.get("type") and args["type"] not in SLUGS:
        abort(400, "Unknown incident type")
    if args.get("status") and args["status"] not in ("pending", "confirmed", "dismissed"):
        abort(400, "Unknown review status")
    query = select(Incident)
    for arg, column in (
        ("type", Incident.slug),
        ("location", Incident.location_id),
        ("status", Incident.review_status),
    ):
        if args.get(arg):
            query = query.where(column == args[arg])
    for arg, operator in (("from", "ge"), ("to", "le")):
        if args.get(arg):
            value = datetime.fromisoformat(args[arg].replace("Z", "+00:00"))
            if value.tzinfo is None:
                abort(400, "Date filters need timezone offsets")
            column = func.coalesce(Incident.start_at, Incident.created_at)
            query = query.where(column >= value if operator == "ge" else column <= value)
    page = max(1, int(args.get("page", 1)))
    limit = min(100, max(1, int(args.get("limit", 25))))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(Incident.created_at.desc(), Incident.id).offset((page - 1) * limit).limit(limit)
    )
    return {"items": [serialize(row) for row in rows], "total": total, "page": page, "limit": limit}


@bp.get("/api/v1/incidents")
@authenticated
def incidents():
    with sessions() as db:
        return jsonify(incident_collection(db, request.args))


@bp.get("/api/v1/incidents/<incident_id>")
@authenticated
def incident_detail(incident_id):
    with sessions() as db:
        incident = record(db, Incident, incident_id)
        return jsonify(
            **serialize(incident),
            evidence=[
                serialize(row) for row in db.scalars(select(Evidence).where(Evidence.incident_id == incident_id))
            ],
            reviews=[
                serialize(row)
                for row in db.scalars(
                    select(Review).where(Review.incident_id == incident_id).order_by(Review.created_at)
                )
            ],
            predictions=[
                serialize(row)
                for row in db.scalars(select(IncidentPrediction).where(IncidentPrediction.incident_id == incident_id))
            ],
        )


@bp.post("/api/v1/incidents/<incident_id>/review")
@authenticated
def review(incident_id):
    valid_identifier(incident_id)
    data = payload()
    if data.get("decision") not in ("confirmed", "dismissed") or len(str(data.get("notes", ""))) > 4000:
        abort(400, "Choose confirmed/dismissed and notes of at most 4000 characters")
    with sessions.begin() as db:
        incident = db.scalar(select(Incident).where(Incident.id == incident_id).with_for_update())
        if not incident:
            abort(404)
        incident.review_status = data["decision"]
        db.add(
            Review(
                incident_id=incident.id,
                reviewer_id=session["user_id"],
                decision=data["decision"],
                notes=str(data.get("notes", "")),
            )
        )
        return jsonify(serialize(incident))


@bp.get("/api/v1/evidence/<evidence_id>")
@authenticated
def evidence(evidence_id):
    with sessions() as db:
        row = record(db, Evidence, evidence_id)
        if row.state != "ready" or not row.path:
            abort(409, f"Evidence is {row.state}")
        path = within(media, row.path)
        if not path.is_file():
            abort(404, "Evidence file missing")
        return send_file(path, conditional=True, mimetype="image/jpeg" if row.kind == "frame" else "video/mp4")
