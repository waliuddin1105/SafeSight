"""Pinned video jobs, cancellation and authenticated result/contract boundaries."""

import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from sqlalchemy import select

from tests.integration.test_api import app  # noqa: F401
from tests.integration.test_supabase_auth import signin
from safesight.storage.schema import AuthSession, Job, utcnow
from safesight.worker.__main__ import Worker
from training.common.fixtures import generate
from tools.build_openapi import build


def submit(app, client, csrf):
    headers = {"X-CSRF-Token": csrf}
    location = client.post("/api/v1/locations", json={"name": "Video test room"}, headers=headers).json
    source = client.post("/api/v1/sources", json={"name": "Recorded tests", "kind": "upload", "location_id": location["id"]}, headers=headers).json
    video = generate("phone_usage") / "videos/test/evaluation_0.mp4"
    result = client.post("/api/v1/uploads", data={"source_id": source["id"], "models": json.dumps(["fire_smoke"]), "evaluation": "true", "file": (io.BytesIO(video.read_bytes()), "test.mp4")}, headers=headers)
    assert result.status_code == 202, result.json
    return result.json, headers


def test_cancel_history_and_auth_protection(app):
    client = app.test_client()
    login = signin(client)
    job, headers = submit(app, client, login.json["csrf_token"])
    assert client.get("/api/v1/jobs").json["total"] == 1
    assert client.get(f"/api/v1/jobs/{job['id']}/video").status_code == 200
    assert app.test_client().get(f"/api/v1/jobs/{job['id']}/predictions").status_code == 401
    cancelled = client.post(f"/api/v1/jobs/{job['id']}/cancel", headers=headers)
    assert cancelled.json["state"] == "cancelled"
    assert client.post(f"/api/v1/jobs/{job['id']}/cancel", headers=headers).status_code == 200
    worker = Worker(app.extensions["safesight"])
    try:
        assert not worker.tick_job()
    finally:
        worker.close()


def test_pinned_job_survives_active_card_replacement_and_cancels_running(app):
    client = app.test_client()
    login = signin(client)
    job, headers = submit(app, client, login.json["csrf_token"])
    root = app.extensions["safesight"]["models_root"]
    card_path = root / "fire_smoke/model_card.json"
    original = card_path.read_text()
    changed = json.loads(original)
    changed["run_id"] = "different-active-run"
    card_path.write_text(json.dumps(changed))
    worker = Worker(app.extensions["safesight"])
    try:
        assert worker.tick()
        predictions = client.get(f"/api/v1/jobs/{job['id']}/predictions").json["items"]
        assert predictions and predictions[0]["predictions"][0]["model_version"] == "untrained-inference-fixture-v1"
        client.post(f"/api/v1/jobs/{job['id']}/cancel", headers=headers)
        worker.tick()
        assert client.get(f"/api/v1/jobs/{job['id']}").json["state"] == "cancelled"
    finally:
        worker.close()
        card_path.write_text(original)


def test_shared_rate_limit_is_atomic(app):
    from safesight.backend.limits import login_limit
    def attempt(_):
        with app.app_context():
            return login_limit("synthetic-address")
    with ThreadPoolExecutor(max_workers=4) as executor:
        assert sum(executor.map(attempt, range(15))) == 10


def test_concurrent_refresh_rotates_once(app):
    client = app.test_client()
    assert signin(client).status_code == 200
    cookie = client.get_cookie("session").value
    with app.extensions["db_sessions"].begin() as db:
        db.scalar(select(AuthSession)).token_expires_at = utcnow() - timedelta(seconds=1)
    def request(_):
        local = app.test_client()
        local.set_cookie("session", cookie)
        return local.get("/api/v1/incidents").status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(request, range(2))) == [200, 200]
    assert app.extensions["supabase_auth"].refreshes == 1


def test_openapi_covers_routes_and_public_job_fields(app):
    specification = build(app)
    assert "/api/v1/jobs/{job_id}/cancel" in specification["paths"]
    schema = specification["components"]["schemas"]["processing_jobs"]
    assert "snapshot" in schema["properties"] and "path" not in schema["properties"]
    assert "auth_sessions" not in specification["components"]["schemas"]
    client = app.test_client()
    login = signin(client)
    job, _ = submit(app, client, login.json["csrf_token"])
    assert set(schema["required"]).issubset(job)
    assert client.get("/api/v1/openapi.json").status_code == 200


def test_storage_shortfall_is_507_without_a_job(app, monkeypatch):
    from types import SimpleNamespace
    client = app.test_client()
    login = signin(client)
    headers = {"X-CSRF-Token": login.json["csrf_token"]}
    location = client.post("/api/v1/locations", json={"name": "Storage test"}, headers=headers).json
    source = client.post("/api/v1/sources", json={"name": "Storage recording", "kind": "upload", "location_id": location["id"]}, headers=headers).json
    monkeypatch.setattr("safesight.backend.routes.uploads.shutil.disk_usage", lambda _: SimpleNamespace(free=0))
    response = client.post("/api/v1/uploads", data={"source_id": source["id"], "models": '["fire_smoke"]', "evaluation": "true", "file": (io.BytesIO(b"fixture"), "test.mp4")}, headers=headers)
    assert response.status_code == 507
    assert client.get("/api/v1/jobs").json["total"] == 0


def test_lost_worker_owner_connection_stops_processing(app):
    import pytest
    worker = Worker(app.extensions["safesight"])
    try:
        worker.owner_connection.close()
        with pytest.raises(RuntimeError, match="ownership"):
            worker.tick()
    finally:
        worker.close()
