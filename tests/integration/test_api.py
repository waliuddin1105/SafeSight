"""Authenticated application flow against a disposable, explicitly named test DB."""

import io
import os

from PIL import Image
import pytest
from sqlalchemy import select
from werkzeug.security import generate_password_hash

from safesight.backend.app import create_app
from safesight.config import ROOT
from safesight.contracts import Alert, Candidate
from safesight.storage.schema import Base, User, Incident, Evidence
from safesight.worker.__main__ import Worker
from training.common.fixtures import generate
from tools.generate_inference_fixtures import generate as inference_fixtures


@pytest.fixture
def app(tmp_path):
    url = os.getenv("SAFESIGHT_TEST_DATABASE_URL", "sqlite:///" + str(tmp_path / "test.sqlite"))
    if not url.startswith("sqlite") and not url.endswith("/safesight_test"):
        raise ValueError("Refusing to initialize a non-test database")
    app = create_app(
        {
            "database_url": url,
            "secret_key": "test-secret-" * 5,
            "media_root": tmp_path / "media",
            "models_root": inference_fixtures(),
            "evaluation_mode": True,
        }
    )
    engine = app.extensions["db_engine"]
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with app.extensions["db_sessions"].begin() as db:
        db.add(User(username="admin", password_hash=generate_password_hash("test-password-123"), role="admin"))
    yield app
    engine.dispose()


def test_auth_capture_incident_evidence_and_review(app, monkeypatch):
    client = app.test_client()
    assert client.get("/api/v1/incidents").status_code == 401
    csrf = client.get("/api/v1/auth/me").json["csrf_token"]
    assert client.post("/api/v1/auth/login", json={}).status_code == 403
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "test-password-123"},
        headers={"X-CSRF-Token": csrf},
    )
    assert login.status_code == 200
    headers = {"X-CSRF-Token": login.json["csrf_token"]}
    location = client.post("/api/v1/locations", json={"name": "Test floor"}, headers=headers).json
    source = client.post(
        "/api/v1/sources",
        json={"name": "Test camera", "location_id": location["id"], "kind": "browser"},
        headers=headers,
    ).json
    assert client.post("/api/v1/sources/" + source["id"] + "/start", headers=headers).status_code == 200
    image = io.BytesIO()
    Image.new("RGB", (128, 128)).save(image, "JPEG")
    frame_headers = {**headers, "Content-Type": "image/jpeg", "X-Sequence": "0", "X-Capture-Ms": "1000"}
    assert (
        client.post(
            "/api/v1/sources/" + source["id"] + "/frames", data=image.getvalue(), headers=frame_headers
        ).status_code
        == 202
    )
    assert (
        client.post(
            "/api/v1/sources/" + source["id"] + "/frames", data=image.getvalue(), headers=frame_headers
        ).status_code
        == 409
    )
    # Deterministic decision injection tests persistence; trained models still load and execute.
    monkeypatch.setattr(
        "safesight.inference.engine.Engine.process",
        lambda self, p, people, t: [
            Alert(
                Candidate("fire_smoke", "fire", "scene", 0.99, t, details={"box": [0, 0, 1, 1]}),
                t,
                t,
                "deterministic-event",
            )
        ],
    )
    worker = Worker(app.extensions["safesight"])
    try:
        assert worker.tick()
    finally:
        worker.close()
    worker = Worker(app.extensions["safesight"])
    try:
        assert worker.pending, "Pending evidence must survive worker restart"
        for key in list(worker.buffers):
            worker.flush_clips(100, key, force=True)
    finally:
        worker.close()
    items = client.get("/api/v1/incidents?type=fire_smoke").json
    assert items["total"] == 1
    incident = items["items"][0]
    detail = client.get("/api/v1/incidents/" + incident["id"]).json
    assert len(detail["evidence"]) == 2
    for evidence in detail["evidence"]:
        assert evidence["state"] == "ready"
        assert client.get(evidence["url"]).status_code == 200
    review = client.post(
        "/api/v1/incidents/" + incident["id"] + "/review",
        json={"decision": "confirmed", "notes": "Synthetic integration check"},
        headers=headers,
    )
    assert review.status_code == 200
    assert client.get("/api/v1/incidents?status=confirmed").json["total"] == 1
    assert len(client.get("/api/v1/incidents/" + incident["id"]).json["reviews"]) == 1
    assert client.get("/api/v1/incidents?from=invalid").status_code == 400


def test_uploaded_recording_runs_to_completion(app):
    client = app.test_client()
    token = client.get("/api/v1/auth/me").json["csrf_token"]
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "test-password-123"},
        headers={"X-CSRF-Token": token},
    )
    headers = {"X-CSRF-Token": login.json["csrf_token"]}
    location = client.post("/api/v1/locations", json={"name": "Upload floor"}, headers=headers).json
    source = client.post(
        "/api/v1/sources", json={"name": "Recordings", "location_id": location["id"], "kind": "upload"}, headers=headers
    ).json
    video = generate("phone_usage") / "videos/test/evaluation_0.mp4"
    with video.open("rb") as handle:
        response = client.post(
            "/api/v1/uploads", data={"source_id": source["id"], "file": (handle, "sample.mp4")}, headers=headers
        )
    assert response.status_code == 202
    worker = Worker(app.extensions["safesight"])
    try:
        assert worker.tick()
        assert client.get("/api/v1/jobs/" + response.json["id"]).json["state"] == "running"
    finally:
        worker.close()
    worker = Worker(app.extensions["safesight"])
    try:
        for _ in range(20):
            worker.tick()
            job = client.get("/api/v1/jobs/" + response.json["id"]).json
            if job["state"] in ("completed", "failed"):
                break
        assert job["state"] == "completed", job
    finally:
        worker.close()
