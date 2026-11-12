"""Session login, logout and identity endpoints."""

from __future__ import annotations

from datetime import timedelta
import secrets

from flask import abort, jsonify, request, session
from sqlalchemy import select
from werkzeug.security import check_password_hash

from safesight.storage.schema import (
    User,
    utcnow,
)


from safesight.backend.context import sessions, login_attempts
from safesight.backend.serializers import serialize

from flask import Blueprint
from safesight.backend.security import authenticated
from safesight.backend.validation import payload

bp = Blueprint("auth", __name__)


@bp.get("/api/v1/auth/me")
def me():
    with sessions() as db:
        user = db.get(User, session.get("user_id")) if session.get("user_id") else None
        return jsonify(user=serialize(user) if user and user.active else None, csrf_token=session["csrf"])


@bp.post("/api/v1/auth/login")
def login():
    data = payload()
    key = request.remote_addr or "local"
    start, count = login_attempts.get(key, (utcnow(), 0))
    if utcnow() - start > timedelta(minutes=5):
        start, count = utcnow(), 0
    if count >= 10:
        abort(429, "Too many sign-in attempts; retry in five minutes")
    login_attempts[key] = (start, count + 1)
    with sessions() as db:
        user = db.scalar(select(User).where(User.username == str(data.get("username", ""))))
        if not user or not user.active or not check_password_hash(user.password_hash, str(data.get("password", ""))):
            abort(401, "Invalid username or password")
        session.clear()
        session.update(user_id=user.id, csrf=secrets.token_urlsafe(32))
        session.permanent = True
        login_attempts.pop(key, None)
        return jsonify(user=serialize(user), csrf_token=session["csrf"])


@bp.post("/api/v1/auth/logout")
@authenticated
def logout():
    session.clear()
    return jsonify(ok=True)
