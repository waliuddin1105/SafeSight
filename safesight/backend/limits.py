"""Cross-process fixed-window login limits without storing IP addresses."""

import hashlib
import hmac
from datetime import datetime, timezone
from flask import current_app
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from safesight.backend.context import sessions
from safesight.storage.schema import LoginAttempt


def login_limit(address: str, maximum: int = 10) -> bool:
    """Atomically count a login attempt in the current five-minute window."""
    now = datetime.now(timezone.utc).timestamp()
    window = int(now // 300)
    key = hmac.new(current_app.secret_key.encode(), f"{window}:{address}".encode(), hashlib.sha256).hexdigest()
    insert = pg_insert if current_app.extensions["db_engine"].dialect.name == "postgresql" else sqlite_insert
    with sessions.begin() as db:
        statement = insert(LoginAttempt).values(
            id=key, attempts=1, expires_at=datetime.fromtimestamp((window + 1) * 300, timezone.utc)
        )
        statement = statement.on_conflict_do_update(
            index_elements=[LoginAttempt.id], set_={"attempts": LoginAttempt.attempts + 1}
        ).returning(LoginAttempt.attempts)
        return db.scalar(statement) <= maximum
