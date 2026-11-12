"""Worker/model health and readiness endpoints."""

from __future__ import annotations

from datetime import timedelta, timezone

from flask import jsonify
from sqlalchemy import text

from safesight.contracts import SLUGS
from safesight.storage.schema import (
    SystemState,
    utcnow,
)


from safesight.backend.context import cfg, sessions

from flask import Blueprint
from safesight.backend.security import authenticated

bp = Blueprint("health", __name__)


@bp.get("/api/v1/models")
@authenticated
def models():
    with sessions() as db:
        state = db.get(SystemState, "worker")
        fresh = bool(
            state
            and utcnow() - state.updated_at.replace(tzinfo=timezone.utc)
            < timedelta(seconds=cfg["worker_lease_seconds"])
        )
        return jsonify(
            items=state.value.get("models", {}) if state else {},
            evaluation_mode=cfg["evaluation_mode"],
            worker_alive=fresh,
        )


@bp.get("/api/v1/health/live")
def live():
    return jsonify(status="alive")


@bp.get("/api/v1/health/ready")
def ready():
    with sessions() as db:
        db.execute(text("SELECT 1"))
        worker = db.get(SystemState, "worker")
        fresh = worker and utcnow() - worker.updated_at.replace(tzinfo=timezone.utc) < timedelta(
            seconds=cfg["worker_lease_seconds"]
        )
        states = worker.value.get("models", {}) if worker else {}
        healthy = bool(fresh) and all(states.get(slug, {}).get("ready") for slug in SLUGS)
        return jsonify(
            status="ready" if healthy else "degraded", database=True, worker=bool(fresh), models=states
        ), 200 if healthy else 503
