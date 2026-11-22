"""Supabase-verified identity and SafeSight role enforcement."""

from __future__ import annotations

from datetime import timedelta, timezone
from functools import wraps
import hashlib
from threading import Lock

from flask import abort, current_app, g, session
from sqlalchemy import select

from safesight.backend.context import sessions
from safesight.backend.supabase_auth import AuthRejected, AuthUnavailable
from safesight.storage.schema import AuthSession, User, utcnow


SESSION_LOCKS = tuple(Lock() for _ in range(64))


def aware(value):
    """Normalize SQLite test timestamps and PostgreSQL timestamps consistently."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def session_lock(identifier: str) -> Lock:
    """Bound process-local refresh concurrency without retaining session identifiers."""
    digest = hashlib.sha256(identifier.encode()).digest()
    return SESSION_LOCKS[int.from_bytes(digest[:2], "big") % len(SESSION_LOCKS)]


def valid_session(stored: AuthSession | None, user: User | None, now) -> bool:
    return bool(
        stored
        and user
        and user.active
        and user.supabase_id
        and aware(stored.expires_at) > now
    )


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
    now = utcnow()
    with sessions() as db:
        stored = db.get(AuthSession, sid)
        user = db.get(User, stored.user_id) if stored else None
        if valid_session(stored, user, now):
            refresh_due = aware(stored.token_expires_at) <= now + timedelta(seconds=60)
            verify_due = now - aware(stored.verified_at) >= timedelta(seconds=30)
            if not refresh_due and not verify_due:
                g.safesight_user = user
                return user

    auth = current_app.extensions["supabase_auth"]
    unavailable = False
    with session_lock(sid), sessions.begin() as db:
        stored = db.scalar(select(AuthSession).where(AuthSession.id == sid).with_for_update())
        user = db.get(User, stored.user_id) if stored else None
        now = utcnow()
        if not valid_session(stored, user, now):
            if stored:
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
