"""Request-local access to app-owned resources."""

from pathlib import Path
from flask import current_app
from werkzeug.local import LocalProxy

cfg = LocalProxy(lambda: current_app.extensions["safesight"])
sessions = LocalProxy(lambda: current_app.extensions["db_sessions"])
media = LocalProxy(lambda: Path(cfg["media_root"]))
login_attempts = LocalProxy(lambda: current_app.extensions["login_attempts"])
