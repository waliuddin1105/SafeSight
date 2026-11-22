"""One consistent dashboard snapshot with bounded database traffic."""

from flask import Blueprint, jsonify, request
from sqlalchemy import select

from safesight.backend.context import sessions
from safesight.backend.routes.health import model_state
from safesight.backend.routes.incidents import incident_collection
from safesight.backend.security import authenticated
from safesight.backend.serializers import serialize
from safesight.storage.schema import Location, Source

bp = Blueprint("overview", __name__)


@bp.get("/api/v1/overview")
@authenticated
def overview():
    with sessions() as db:
        return jsonify(
            sources=[serialize(row) for row in db.scalars(select(Source).order_by(Source.name))],
            locations=[serialize(row) for row in db.scalars(select(Location).order_by(Location.name))],
            models=model_state(db),
            incidents=incident_collection(db, request.args),
        )
