"""Authenticated REST API for capture, incident evidence, and human review."""

from __future__ import annotations

from datetime import timedelta
import os
from pathlib import Path

from flask import Flask

from safesight.config import settings
from safesight.storage.database import database


from safesight.backend.errors import register_handlers
from safesight.backend.cli import create_user
from safesight.backend.routes import auth, sources, uploads, incidents, health, frontend


def create_app(overrides: dict | None = None) -> Flask:
    """Create the application; migrations and user creation are explicit commands."""
    cfg = {**settings(), **(overrides or {})}
    if len(cfg["secret_key"]) < 32:
        raise ValueError("SECRET_KEY must contain at least 32 characters; set it in .env")
    app = Flask(__name__, static_folder=None)
    app.config.update(
        SECRET_KEY=cfg["secret_key"],
        MAX_CONTENT_LENGTH=cfg["max_upload_bytes"],
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )
    engine, sessions = database(cfg["database_url"])
    app.extensions.update(safesight=cfg, db_engine=engine, db_sessions=sessions)
    media = Path(cfg["media_root"])
    media.mkdir(parents=True, exist_ok=True)
    app.extensions["login_attempts"] = {}

    register_handlers(app)
    app.register_blueprint(auth.bp)
    app.register_blueprint(sources.bp)
    app.register_blueprint(uploads.bp)
    app.register_blueprint(incidents.bp)
    app.register_blueprint(health.bp)
    app.register_blueprint(frontend.bp)
    app.cli.add_command(create_user)
    return app
