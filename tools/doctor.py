"""Read-only deployment diagnostics without exposing credentials or tokens."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import inspect, select, text
from safesight.backend.supabase_auth import SupabaseAuth
from safesight.config import settings
from safesight.storage.database import database
from safesight.storage.schema import Base, User
from safesight.contracts import SLUGS
from safesight.model_loaders.registry import Registry


def main() -> int:
    cfg = settings()
    report = {
        "secret_configured": len(cfg["secret_key"]) >= 32,
        "secure_cookies_required": "Set SESSION_COOKIE_SECURE=true behind HTTPS",
        "models": {},
    }
    engine = None
    try:
        engine, sessions = database(cfg["database_url"])
        with engine.connect() as conn:
            report["database"] = True
            report["tls"] = bool(conn.connection.driver_connection.pgconn.ssl_in_use)
            report["migration"] = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            secured = set(
                conn.execute(
                    text("SELECT relname FROM pg_class WHERE relnamespace='public'::regnamespace AND relrowsecurity")
                ).scalars()
            )
            report["tables_without_rls"] = sorted(set(Base.metadata.tables) - secured)
            report["missing_tables"] = sorted(set(Base.metadata.tables) - set(inspect(conn).get_table_names()))
            report["active_profiles"] = len(
                list(conn.execute(select(User.id).where(User.active.is_(True), User.supabase_id.is_not(None))))
            )
        client = SupabaseAuth(cfg["supabase_url"], cfg["supabase_publishable_key"])
        report["auth_available"] = bool(client.request("settings"))
        registry = Registry(cfg["models_root"], evaluation=True, lazy=True)
        try:
            for slug in SLUGS:
                state = registry.status[slug]
                report["models"][slug] = (
                    "invalid_card_or_artifact"
                    if not state.get("ready") and state.get("available_versions") is None
                    else "missing"
                    if not state.get("ready")
                    else "evaluation_only"
                    if state.get("evaluation_only")
                    else "qualified"
                )
        finally:
            registry.close()
    except Exception as error:
        report["error"] = type(error).__name__
        report["message"] = "Check database/Auth settings, network and migrations; credential details suppressed"
    finally:
        if engine:
            engine.dispose()
    print(json.dumps(report, indent=2))
    return int("error" in report or not report["secret_configured"] or bool(report.get("missing_tables")))


if __name__ == "__main__":
    raise SystemExit(main())
