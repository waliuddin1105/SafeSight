"""Preparation checks with local synthetic archives/HTTP only; no training/downloads."""

from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import zipfile

import pytest

from training.common.dataset_preparation import archive_path, download, extract, file_hash, install_native, prepare
from tools.prepare_datasets import main


@pytest.fixture
def server(request):
    data = b"local synthetic HTTP fixture" * 100
    if getattr(request, "param", None) == "zip":
        import io

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("data.yaml", "names: [person, phone]\n")
        data = buffer.getvalue()
    ranges = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            ranges.append(self.headers.get("Range"))
            offset = int(self.headers.get("Range", "bytes=0-").split("=")[1].split("-")[0])
            partial = self.headers.get("Range") and self.path != "/ignore-range"
            self.send_response(206 if partial else 200)
            self.send_header("ETag", '"fixture-v1"')
            self.send_header("Content-Type", "application/octet-stream")
            if partial:
                self.send_header("Content-Range", f"bytes {offset}-{len(data) - 1}/{len(data)}")
            else:
                offset = 0
            self.send_header("Content-Length", str(len(data) - offset))
            self.end_headers()
            self.wfile.write(data[offset:])

        def log_message(self, *args):
            pass

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{http.server_port}", data, ranges
    http.shutdown()
    http.server_close()
    thread.join()


@pytest.mark.parametrize("endpoint", ["/resume", "/ignore-range"])
def test_resumed_download_and_range_ignored(server, tmp_path, endpoint):
    base, data, ranges = server
    url = base + endpoint
    target = tmp_path / "source.archive"
    target.with_suffix(".part").write_bytes(data[:37])
    target.with_suffix(".http.json").write_text(
        json.dumps({"url_hash": hashlib.sha256(url.encode()).hexdigest(), "validator": '"fixture-v1"'})
    )
    expected = hashlib.sha256(data).hexdigest()
    receipt = download(url, target, {}, expected, 0, len(data))
    assert receipt["sha256"] == expected
    assert target.read_bytes() == data
    assert ranges == ["bytes=37-"]
    assert download(url, target, {}, expected, 0, len(data))["cached"]
    assert len(ranges) == 1


def test_checksum_failure_does_not_publish_archive(server, tmp_path):
    url, data, _ = server
    target = tmp_path / "data.archive"
    with pytest.raises(ValueError, match="SHA-256"):
        download(url, target, {}, "0" * 64, 0, len(data))
    assert not target.exists()
    assert not target.with_suffix(".part").exists()


def test_low_space_prevents_network_access(tmp_path, monkeypatch):
    monkeypatch.setattr("training.common.dataset_preparation.shutil.disk_usage", lambda _: SimpleNamespace(free=0))
    with pytest.raises(ValueError, match="Insufficient"):
        download("https://invalid.example/data.zip", tmp_path / "data.archive", {}, None, 100, 1000)


@pytest.mark.parametrize("server", ["zip"], indirect=True)
def test_cached_provider_export_does_not_need_fresh_credentials(server, tmp_path, monkeypatch):
    url, _, requests = server
    source = {
        "id": "fixture-http",
        "title": "local test",
        "kind": "http",
        "url": url + "/archive",
        "publisher": "https://example.invalid/publisher",
        "license": "test only",
        "estimated_archive_gb": 0,
        "annotation_gaps": ["events missing"],
    }
    first = prepare(source, "phone_usage", tmp_path / "datasets", tmp_path / "cache", 0, 10000)
    assert first["status"] == "DOWNLOADED_NEEDS_ANNOTATIONS"
    monkeypatch.setattr(
        "training.common.dataset_preparation.source_url",
        lambda _: pytest.fail("Cached archives must not resolve credentials again"),
    )
    second = prepare(source, "phone_usage", tmp_path / "datasets", tmp_path / "cache", 0, 10000)
    assert second["archive"]["cached"]
    assert len(requests) == 1


@pytest.mark.parametrize(
    "name", ["../escape", "/absolute", "C:/escape", "a\\..\\escape", "NUL.txt", "folder./data", ".extracted.json"]
)
def test_archive_paths_are_portable_and_contained(name):
    with pytest.raises(ValueError):
        archive_path(name)


def make_zip(path: Path, files: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as handle:
        for name, data in files.items():
            handle.writestr(name, data)
    return path


def test_extraction_is_idempotent_and_resumes(tmp_path):
    archive = make_zip(tmp_path / "data.zip", {"images/a.txt": b"one", "images/b.txt": b"two"})
    target = tmp_path / "expanded"
    (target / "images").mkdir(parents=True)
    (target / ".extracting.json").write_text(json.dumps({"archive_sha256": file_hash(archive)}))
    (target / "images/a.txt").write_bytes(b"one")
    extract(archive, target, 0, 1000)
    assert (target / "images/b.txt").read_bytes() == b"two"
    before = (target / "images/a.txt").stat().st_mtime_ns
    extract(archive, target, 0, 1000)
    assert (target / "images/a.txt").stat().st_mtime_ns == before


def test_archive_cannot_escape_destination(tmp_path):
    archive = make_zip(tmp_path / "bad.zip", {"../outside.txt": b"no"})
    with pytest.raises(ValueError):
        extract(archive, tmp_path / "expanded", 0, 1000)
    assert not (tmp_path / "outside.txt").exists()


def test_native_install_preserves_user_data(tmp_path, monkeypatch):
    monkeypatch.setattr("training.common.splitting.materialize_splits", lambda root, slug: root)
    source = tmp_path / "source"
    source.mkdir()
    (source / "manifest.jsonl").write_text("component fixture; validator mocked")
    (source / "data.yaml").write_text("new dataset")
    target = tmp_path / "target"
    target.mkdir()
    (target / "data.yaml").write_text("existing user dataset")
    result = SimpleNamespace(valid=True, errors=[], warnings=[], dataset_hash="fixture")
    monkeypatch.setattr("training.common.datasets.validate", lambda *args: result)
    with pytest.raises(ValueError, match="overwrite"):
        install_native(source, target, "phone_usage")
    assert (target / "data.yaml").read_text() == "existing user dataset"


def test_public_partial_labels_never_become_ready(tmp_path):
    archive = make_zip(
        tmp_path / "partial.zip",
        {"data.yaml": b"names: [cigarette, smoke, person]\n", "train/labels/a.txt": b"0 .5 .5 .2 .2"},
    )
    source = {
        "id": "fixture",
        "publisher": "synthetic local fixture",
        "license": "test only",
        "annotation_gaps": ["lighter/event annotations missing"],
    }
    result = prepare(source, "cigarette_smoking", tmp_path / "datasets", tmp_path / "cache", 0, 10000, archive)
    assert result["status"] == "DOWNLOADED_NEEDS_ANNOTATIONS"
    assert "lighter" in result["inventory"]["required_classes_not_declared"]
    assert not (tmp_path / "datasets/cigarette_smoking/manifest.jsonl").exists()


def test_plan_mode_has_no_dataset_writes(tmp_path):
    target = tmp_path / "not-created"
    assert main(["all", "--plan", "--datasets-root", str(target)]) == 0
    assert not target.exists()


def test_reviewed_native_bundle_installs_and_emits_config_without_training(tmp_path, monkeypatch):
    monkeypatch.setattr("training.common.splitting.materialize_splits", lambda root, slug: root)
    import yaml
    from tools import prepare_datasets

    source = {
        "id": "component-fixture",
        "title": "Explicit component fixture",
        "publisher": "local unit test",
        "license": "test only",
        "kind": "http",
        "url": "https://invalid.example/not-requested",
        "annotation_gaps": [],
    }
    config = tmp_path / "sources.yaml"
    config.write_text(
        yaml.safe_dump(
            {"schema_version": 1, "minimum_free_gb": 0, "maximum_extracted_gb": 1, "sources": {"phone_usage": source}}
        )
    )
    archive = make_zip(
        tmp_path / "native.zip",
        {
            "phone_usage/manifest.jsonl": b"explicit validation-boundary fixture",
            "phone_usage/data.yaml": b"names: [person, phone]\n",
        },
    )
    validation = SimpleNamespace(valid=True, errors=[], warnings=[], dataset_hash="component-fixture-hash")
    monkeypatch.setattr("training.common.datasets.validate", lambda *args: validation)
    monkeypatch.setattr(
        "training.common.dataset_preparation.shutil.disk_usage", lambda _: SimpleNamespace(free=10 * 1024**3)
    )
    monkeypatch.setattr(prepare_datasets, "ROOT", tmp_path)
    dataset_root = tmp_path / "datasets"
    assert (
        main(
            [
                "phone_usage",
                "--config",
                str(config),
                "--datasets-root",
                str(dataset_root),
                "--archive",
                f"phone_usage={archive}",
            ]
        )
        == 0
    )
    assert (dataset_root / "phone_usage/manifest.jsonl").exists()
    report = json.loads((tmp_path / "artifacts/dataset-preparation/report.json").read_text())
    assert report["training_executed"] is False
    assert report["datasets"]["phone_usage"]["status"] == "READY"
    recipe = yaml.safe_load((tmp_path / "artifacts/dataset-preparation/phone_usage.yaml").read_text())
    assert recipe["dataset"] == str(dataset_root / "phone_usage")
    monkeypatch.setattr(
        "training.common.dataset_preparation.source_url", lambda _: pytest.fail("Ready datasets must not re-download")
    )
    assert main(["phone_usage", "--config", str(config), "--datasets-root", str(dataset_root)]) == 0
