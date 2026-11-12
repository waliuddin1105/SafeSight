"""Explicit one-time Supabase admin provisioning; never a production login bypass."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select, text
from safesight.backend.supabase_auth import SupabaseAuth, AuthRejected, AuthUnavailable
from safesight.config import ROOT, settings
from safesight.storage.database import database
from safesight.storage.schema import User


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default="admin@safesight.local")
    args = parser.parse_args()
    cfg = settings()
    key = os.getenv("SUPABASE_SECRET_KEY", "")
    if not key.startswith("sb_secret_"):
        raise SystemExit(
            "Set SUPABASE_SECRET_KEY in the ignored .env for explicit provisioning; publishable keys cannot create confirmed users"
        )
    path = ROOT / "artifacts/private/admin-credentials.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    project = hashlib.sha256(cfg["supabase_url"].encode()).hexdigest()
    client = SupabaseAuth(cfg["supabase_url"], key)
    if path.exists():
        credentials = json.loads(path.read_text())
        if credentials["project"] != project or credentials["email"] != args.email:
            raise SystemExit("Existing credential file belongs to another account/project; preserved")
    else:
        credentials = {"project": project, "email": args.email, "password": secrets.token_urlsafe(30)}
        # Reserve the local credential file before remote side effects so retries
        # retain the same generated password. It is excluded from Git and Docker.
        with path.open("x", encoding="utf-8") as handle:
            json.dump(credentials, handle, indent=2)
        path.chmod(0o600)
    engine, sessions = database(cfg["database_url"])
    try:
        with engine.connect() as conn:
            subject = conn.execute(
                text("SELECT id FROM auth.users WHERE lower(email)=lower(:email)"), {"email": args.email}
            ).scalar_one_or_none()
        if subject is None:
            identity = client.request(
                "admin/users",
                {"email": credentials["email"], "password": credentials["password"], "email_confirm": True},
            )
            subject = identity.get("id") or identity["user"]["id"]
        # Verify the stored password without resetting any existing account.
        public = SupabaseAuth(cfg["supabase_url"], cfg["supabase_publishable_key"])
        tokens = public.login(credentials["email"], credentials["password"])
        verified = public.user(tokens["access_token"])
        if verified["id"] != str(subject):
            raise SystemExit("Account identity mismatch; no application access granted")
        try:
            with sessions.begin() as db:
                user = db.scalar(select(User).where(User.supabase_id == str(subject)))
                if user is None:
                    if db.scalar(select(User).where(User.username == args.email)):
                        raise SystemExit("Existing profile email conflict; no profile rebound")
                    user = User(username=args.email, supabase_id=str(subject))
                    db.add(user)
                user.role, user.active = "admin", True
            credentials["supabase_id"] = str(subject)
            path.write_text(json.dumps(credentials, indent=2), encoding="utf-8")
            print(f"Default admin provisioned. Credentials saved only to {path}; password not printed")
        finally:
            try:
                public.logout(tokens["access_token"])
            except (AuthRejected, AuthUnavailable):
                pass
    except (AuthRejected, AuthUnavailable):
        raise SystemExit(
            "Admin provisioning/credential verification failed; existing credentials preserved, no secrets printed"
        ) from None
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
