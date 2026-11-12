"""Request payload and record lookup validation."""

from __future__ import annotations


from flask import abort, request


def payload() -> dict:
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        abort(400, "Expected a JSON object")
    return value


def valid_identifier(key):
    if not isinstance(key, str):
        abort(400, "Invalid record identifier")
    try:
        from uuid import UUID

        UUID(key)
    except (ValueError, TypeError):
        abort(400, "Invalid record identifier")
    return key


def record(db, kind, key):
    valid_identifier(key)
    value = db.get(kind, key)
    if value is None:
        abort(404, "Record not found")
    return value
