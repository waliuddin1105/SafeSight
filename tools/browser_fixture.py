"""Run explicit browser acceptance fixtures against a disposable test database only."""

from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if __name__ == "__main__":
    from waitress import serve
    from sqlalchemy import select
    from safesight.backend.app import create_app
    from safesight.storage.schema import Base, User, Location
    from tools.generate_inference_fixtures import generate
    from tests.auth_fixture import FakeAuth, SUBJECT, EMAIL

    url = os.getenv("SAFESIGHT_TEST_DATABASE_URL", "")
    if not url.endswith("/safesight_test"):
        raise SystemExit("Requires an explicitly named disposable safesight_test PostgreSQL database")
    app = create_app(
        {
            "database_url": url,
            "secret_key": "browser-fixture-only-" * 3,
            "supabase_url": "https://auth.example.test",
            "supabase_publishable_key": "sb_publishable_fixture",
            "models_root": generate(),
            "evaluation_mode": True,
        }
    )
    app.extensions["supabase_auth"] = FakeAuth()
    Base.metadata.create_all(app.extensions["db_engine"])
    with app.extensions["db_sessions"].begin() as db:
        user = db.scalar(select(User).where(User.supabase_id == SUBJECT))
        if user is None:
            user = User(username=EMAIL, supabase_id=SUBJECT)
            db.add(user)
        user.role, user.active = "admin", True
        if not db.scalar(select(Location)):
            db.add(Location(name="Browser fixture location"))
    serve(app, host="127.0.0.1", port=5000)
