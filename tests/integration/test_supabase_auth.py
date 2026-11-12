"""Supabase identity/session boundaries exercised with an explicit provider fake."""

from datetime import timedelta

from sqlalchemy import select

from tests.integration.test_api import app  # noqa: F401 -- shared disposable database fixture
from tests.auth_fixture import EMAIL
from safesight.storage.schema import AuthSession, User, utcnow


def signin(client):
    csrf = client.get("/api/v1/auth/me").json["csrf_token"]
    return client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": "test-password-123"}, headers={"X-CSRF-Token": csrf}
    )


def test_tokens_are_backend_only_refresh_and_logout(app):
    client = app.test_client()
    login = signin(client)
    assert login.status_code == 200
    assert "access_token" not in login.json and "refresh_token" not in login.json
    with client.session_transaction() as cookie:
        assert "access_token" not in cookie and "refresh_token" not in cookie
        sid = cookie["auth_session"]
    with app.extensions["db_sessions"].begin() as db:
        stored = db.get(AuthSession, sid)
        stored.token_expires_at = utcnow() - timedelta(seconds=1)
    assert client.get("/api/v1/incidents").status_code == 200
    assert app.extensions["supabase_auth"].refreshes == 1
    result = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": login.json["csrf_token"]})
    assert result.status_code == 200
    assert client.get("/api/v1/incidents").status_code == 401
    with app.extensions["db_sessions"]() as db:
        assert db.get(AuthSession, sid) is None


def test_unknown_and_disabled_profiles_cannot_enter(app):
    with app.extensions["db_sessions"].begin() as db:
        user = db.scalar(select(User))
        user.active = False
    assert signin(app.test_client()).status_code == 403


def test_invalid_password_and_csrf_are_rejected(app):
    client = app.test_client()
    csrf = client.get("/api/v1/auth/me").json["csrf_token"]
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": EMAIL, "password": "wrong"}, headers={"X-CSRF-Token": csrf}
        ).status_code
        == 401
    )
    assert client.post("/api/v1/auth/login", json={"email": EMAIL, "password": "test-password-123"}).status_code == 403


def test_provider_rejection_and_outage_fail_closed(app):
    client = app.test_client()
    assert signin(client).status_code == 200
    with app.extensions["db_sessions"].begin() as db:
        stored = db.scalar(select(AuthSession))
        stored.verified_at = utcnow() - timedelta(seconds=31)
    provider = app.extensions["supabase_auth"]
    provider.unavailable = True
    assert client.get("/api/v1/incidents").status_code == 503
    provider.unavailable = False
    provider.revoked = True
    assert client.get("/api/v1/incidents").status_code == 401


def test_reviewer_cannot_create_sources_and_disabled_access_is_immediate(app):
    client = app.test_client()
    login = signin(client)
    with app.extensions["db_sessions"].begin() as db:
        user = db.scalar(select(User))
        user.role = "reviewer"
    assert (
        client.post(
            "/api/v1/locations", json={"name": "Forbidden"}, headers={"X-CSRF-Token": login.json["csrf_token"]}
        ).status_code
        == 403
    )
    with app.extensions["db_sessions"].begin() as db:
        db.scalar(select(User)).active = False
    assert client.get("/api/v1/incidents").status_code == 401


def test_refresh_rotation_survives_identity_service_outage(app):
    client = app.test_client()
    assert signin(client).status_code == 200
    with app.extensions["db_sessions"].begin() as db:
        db.scalar(select(AuthSession)).token_expires_at = utcnow() - timedelta(seconds=1)
    provider = app.extensions["supabase_auth"]
    provider.unavailable = True
    assert client.get("/api/v1/incidents").status_code == 503
    with app.extensions["db_sessions"]() as db:
        assert db.scalar(select(AuthSession)).access_token == "fixture-refreshed"
    provider.unavailable = False
    assert client.get("/api/v1/incidents").status_code == 200
    assert provider.refreshes == 1


def test_unprovisioned_supabase_identity_does_not_self_enroll(app):
    with app.extensions["db_sessions"].begin() as db:
        db.scalar(select(User)).supabase_id = None
    assert signin(app.test_client()).status_code == 403
    with app.extensions["db_sessions"]() as db:
        assert db.scalar(select(AuthSession)) is None
