"""Supabase email login with opaque, HttpOnly SafeSight browser sessions."""

from datetime import timedelta
import secrets
from uuid import UUID

from flask import Blueprint, abort, current_app, jsonify, request, session
from sqlalchemy import delete, select

from safesight.backend.context import sessions, login_attempts
from safesight.backend.security import current_user
from safesight.backend.serializers import serialize
from safesight.backend.supabase_auth import AuthRejected, AuthUnavailable
from safesight.backend.validation import payload
from safesight.storage.schema import AuthSession, User, utcnow

bp = Blueprint("auth", __name__)


@bp.get("/api/v1/auth/me")
def me():
    user = current_user()
    return jsonify(user=serialize(user) if user else None, csrf_token=session["csrf"])


@bp.post("/api/v1/auth/login")
def login():
    data = payload()
    email, password = data.get("email"), data.get("password")
    if not isinstance(email, str) or not isinstance(password, str) or len(email) > 320 or not password:
        abort(400, "Email and password are required")
    key = request.remote_addr or "local"
    now = utcnow()
    # Bound memory and remove expired buckets without retaining raw credentials.
    for address, (started, _) in list(login_attempts.items()):
        if now - started > timedelta(minutes=5):
            login_attempts.pop(address, None)
    start, count = login_attempts.get(key, (now, 0))
    if count >= 10 or len(login_attempts) >= 10000:
        abort(429, "Too many sign-in attempts; retry later")
    login_attempts[key] = (start, count + 1)
    auth = current_app.extensions["supabase_auth"]
    try:
        tokens = auth.login(email.strip(), password)
        identity = auth.user(tokens["access_token"])
        subject = str(UUID(identity["id"]))
    except AuthRejected:
        abort(401, "Invalid email/password or account not confirmed")
    except AuthUnavailable:
        abort(503, "Authentication service unavailable; retry shortly")
    with sessions.begin() as db:
        user = db.scalar(select(User).where(User.supabase_id == subject))
        if not user or not user.active:
            # Do not enroll arbitrary public Supabase signups or trust user_metadata roles.
            try:
                auth.logout(tokens["access_token"])
            except (AuthRejected, AuthUnavailable):
                pass
            abort(403, "Your account has not been granted SafeSight access")
        if session.get("auth_session"):
            db.execute(delete(AuthSession).where(AuthSession.id == session["auth_session"]))
        db.execute(delete(AuthSession).where(AuthSession.expires_at < now))
        sid = secrets.token_hex(32)
        db.add(
            AuthSession(
                id=sid,
                user_id=user.id,
                access_token=tokens["access_token"],
                refresh_token=tokens["refresh_token"],
                token_expires_at=now + timedelta(seconds=int(tokens["expires_in"])),
                expires_at=now + timedelta(hours=8),
                verified_at=now,
            )
        )
        session.clear()
        session.update(auth_session=sid, user_id=user.id, csrf=secrets.token_urlsafe(32))
        session.permanent = True
        login_attempts.pop(key, None)
        return jsonify(user=serialize(user), csrf_token=session["csrf"])


@bp.post("/api/v1/auth/logout")
def logout():
    # Local logout always works, including after expiry or a provider outage.
    with sessions.begin() as db:
        stored = db.get(AuthSession, session.get("auth_session", ""))
        if stored:
            try:
                current_app.extensions["supabase_auth"].logout(stored.access_token)
            except (AuthRejected, AuthUnavailable):
                pass
            db.delete(stored)
    session.clear()
    return jsonify(ok=True)
