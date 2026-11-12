"""Supabase-verified identity and SafeSight role enforcement."""

from __future__ import annotations

from datetime import timedelta, timezone
from functools import wraps

from flask import abort, current_app, g, session
from sqlalchemy import select

from safesight.backend.context import sessions
from safesight.backend.supabase_auth import AuthRejected, AuthUnavailable
from safesight.storage.schema import AuthSession, User, utcnow


def aware(value):
    """Normalize SQLite test timestamps and PostgreSQL timestamps consistently."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def current_user() -> User | None:
    """Check local access each request; revalidate Supabase identity every 30 seconds.

    A row lock serializes refresh-token rotation across web processes. Provider outages
    return 503 without destroying the session. Supabase rejection destroys it.
    """
    if hasattr(g, "safesight_user"):
        return g.safesight_user
    sid = session.get("auth_session")
    g.safesight_user = None
    if not sid:
        return None
    auth = current_app.extensions["supabase_auth"]
    unavailable = False
    with sessions.begin() as db:
        stored = db.scalar(select(AuthSession).where(AuthSession.id == sid).with_for_update())
        if not stored:
            return None
        user = db.get(User, stored.user_id)
        now = utcnow()
        if not user or not user.active or not user.supabase_id or aware(stored.expires_at) <= now:
            db.delete(stored)
            return None
        try:
            if aware(stored.token_expires_at) <= now + timedelta(seconds=60):
                tokens = auth.refresh(stored.refresh_token)
                stored.access_token, stored.refresh_token = tokens["access_token"], tokens["refresh_token"]
                stored.token_expires_at = now + timedelta(seconds=int(tokens["expires_in"]))
                stored.verified_at = now - timedelta(seconds=31)
            if now - aware(stored.verified_at) >= timedelta(seconds=30):
                identity = auth.user(stored.access_token)
                if identity.get("id") != user.supabase_id:
                    raise AuthRejected("Session identity changed")
                stored.verified_at = now
        except AuthRejected:
            db.delete(stored)
            return None
        except AuthUnavailable:
            # Persist any successfully rotated tokens even if the subsequent identity
            # check failed; rolling them back can lose the new refresh token.
            unavailable = True
        if not unavailable:
            g.safesight_user = user
    if unavailable:
        abort(503, "Authentication service unavailable; retry shortly")
    return g.safesight_user


def authenticated(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            abort(401, "Sign in to continue")
        return function(*args, **kwargs)

    return wrapped


def admin() -> None:
    user = current_user()
    if not user or user.role != "admin":
        abort(403, "Administrator role required")
