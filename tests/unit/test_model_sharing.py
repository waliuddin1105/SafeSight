"""Transfer integrity tests using inert bytes, never training or executing weights."""

import json

import pytest

from safesight.contracts import CLASSES
from tools.share_model import export_model, fetch_model
from training.common.dataset_preparation import file_hash


def fixture(root):
    version = root / "body_state/versions/test-run"
    version.mkdir(parents=True)
    artifact = version / "model.ts"
    artifact.write_bytes(b"inert synthetic fixture, not executable weights")
    card = dict(
        schema_version=1,
        slug="body_state",
        run_id="test-run",
        loader="torchscript",
        architecture="fixture",
        classes=CLASSES["body_state"],
        input_size=32,
        artifact="body_state/versions/test-run/model.ts",
        sha256=file_hash(artifact),
        thresholds={},
        quality={"status": "FAIL"},
        synthetic=True,
    )
    (version / "model_card.json").write_text(json.dumps(card))


def test_transfer_preserves_card_quality_and_never_activates(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    fixture(source)
    archive = tmp_path / "shared.zip"
    checksum = export_model(source, "body_state", "test-run", archive)
    destination = fetch_model(target, str(archive), checksum)
    assert json.loads((destination / "model_card.json").read_text())["quality"]["status"] == "FAIL"
    assert not (target / "body_state/model_card.json").exists()
    assert fetch_model(target, str(archive), checksum) == destination
    (destination / "model.ts").write_bytes(b"existing model changed")
    with pytest.raises(ValueError, match="overwrite"):
        fetch_model(target, str(archive), checksum)


def test_bad_bundle_hash_and_escaping_artifact_are_rejected(tmp_path):
    root = tmp_path / "source"
    fixture(root)
    archive = tmp_path / "shared.zip"
    export_model(root, "body_state", "test-run", archive)
    with pytest.raises(ValueError, match="checksum mismatch"):
        fetch_model(tmp_path / "target", str(archive), "0" * 64)
    assert not (tmp_path / "target/body_state").exists()
    path = root / "body_state/versions/test-run/model_card.json"
    card = json.loads(path.read_text())
    card["artifact"] = "../outside.ts"
    path.write_text(json.dumps(card))
    with pytest.raises(ValueError, match="escapes"):
        export_model(root, "body_state", "test-run", tmp_path / "bad.zip")
