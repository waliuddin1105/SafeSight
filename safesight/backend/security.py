"""Authentication and role checks shared by resource blueprints."""

from __future__ import annotations

from functools import wraps

from flask import abort, session

from safesight.storage.schema import (
    User,
)


from safesight.backend.context import sessions


def authenticated(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with sessions() as db:
            user = db.get(User, session.get("user_id")) if session.get("user_id") else None
            if not user or not user.active:
                abort(401, "Sign in to continue")
        return function(*args, **kwargs)

    return wrapped


def admin() -> None:
    with sessions() as db:
        user = db.get(User, session["user_id"])
        if user.role != "admin":
            abort(403, "Administrator role required")
