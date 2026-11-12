"""Prune expired auth records and old orphan uploads; evidence is always preserved."""

import argparse
from datetime import timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import delete, select
from safesight.config import settings, within
from safesight.storage.database import database
from safesight.storage.schema import AuthSession, Job, LoginAttempt, utcnow


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Default is dry-run")
    args = parser.parse_args()
    cfg = settings()
    engine, sessions = database(cfg["database_url"])
    with sessions.begin() as db:
        retained = set(db.scalars(select(Job.path)))
        expired = list(db.scalars(select(AuthSession.id).where(AuthSession.expires_at < utcnow())))
        print(f"Expired sessions: {len(expired)}; apply={args.apply}")
        if args.apply:
            db.execute(delete(AuthSession).where(AuthSession.expires_at < utcnow()))
            db.execute(delete(LoginAttempt).where(LoginAttempt.expires_at < utcnow()))
    threshold = (utcnow() - timedelta(days=1)).timestamp()
    root = cfg["media_root"]
    for path in (root / "uploads").glob("*"):
        if path.is_file() and path.relative_to(root).as_posix() not in retained and path.stat().st_mtime < threshold:
            print("Orphan upload: " + path.name)
            if args.apply:
                within(root, path.relative_to(root)).unlink()
    engine.dispose()
    print("Incident evidence was preserved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
