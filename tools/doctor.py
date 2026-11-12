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
from safesight.contracts import SLUGS, CLASSES
from safesight.model_loaders.registry import ModelCard
from training.common.datasets import sha256
from safesight.config import within


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
        for slug in SLUGS:
            card = cfg["models_root"] / slug / "model_card.json"
            if not card.is_file():
                report["models"][slug] = "missing"
                continue
            try:
                parsed = ModelCard.model_validate_json(card.read_text())
                if (
                    parsed.slug != slug
                    or parsed.classes != CLASSES[slug]
                    or sha256(within(cfg["models_root"], parsed.artifact)) != parsed.sha256
                ):
                    raise ValueError("Artifact/card mismatch")
                pose = within(cfg["models_root"], "_pretrained/pose_landmarker_lite.task")
                expected_pose = (parsed.model_extra or {}).get("context_asset_sha256")
                if expected_pose and (not pose.is_file() or sha256(pose) != expected_pose):
                    raise ValueError("Pose preprocessing asset mismatch")
                report["models"][slug] = (
                    "qualified"
                    if parsed.quality.get("status") == "PASS" and not parsed.synthetic
                    else "evaluation_only"
                )
            except (ValueError, OSError):
                report["models"][slug] = "invalid_card_or_artifact"
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
