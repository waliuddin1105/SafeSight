"""Session protection, response headers and centralized error handlers."""

from __future__ import annotations

import hmac
import secrets
from urllib.parse import urlparse

from flask import abort, jsonify, request, session
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.exceptions import HTTPException


from flask import current_app as app


def protect_session():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), session["csrf"]):
            abort(403, "Missing or invalid CSRF token")
        origin = request.headers.get("Origin")
        if origin and urlparse(origin).netloc != request.host:
            abort(403, "Cross-origin mutation rejected")


def headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    return response


def http_error(error):
    return jsonify(error={"code": error.code, "message": error.description}), error.code


def validation_error(error):
    return jsonify(error={"code": 400, "message": str(error)}), 400


def storage_error(error):
    app.logger.exception("Media storage operation failed")
    return jsonify(error={"code": 507, "message": "Media storage unavailable"}), 507


def conflict(error):
    app.logger.warning("Database constraint rejected request: %s", error.orig)
    return jsonify(error={"code": 409, "message": "Record conflicts with existing data"}), 409


def database_error(error):
    app.logger.exception("Database operation failed")
    return jsonify(error={"code": 503, "message": "Database unavailable"}), 503


def register_handlers(app):
    app.before_request(protect_session)
    app.after_request(headers)
    app.errorhandler(HTTPException)(http_error)
    app.errorhandler(ValueError)(validation_error)
    app.errorhandler(OSError)(storage_error)
    app.errorhandler(IntegrityError)(conflict)
    app.errorhandler(SQLAlchemyError)(database_error)
