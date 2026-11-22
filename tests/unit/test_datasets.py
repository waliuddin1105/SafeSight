"""Dataset contract regression tests using generated artificial media only."""

import json
import shutil

import pytest

from training.common.datasets import sha256, validate, validate_event_record, valid_yolo_box
from training.common.fixtures import generate


@pytest.fixture
def data(tmp_path):
    return shutil.copytree(generate("phone_usage"), tmp_path / "phone_usage")


def test_read_only_and_negative_label(data):
    before = {str(p): (sha256(p), p.stat().st_mtime_ns) for p in data.rglob("*") if p.is_file()}
    assert validate(data, "phone_usage", True).valid
    after = {str(p): (sha256(p), p.stat().st_mtime_ns) for p in data.rglob("*") if p.is_file()}
    assert before == after
    (data / "labels/train/train_0_0.txt").write_text("")
    assert validate(data, "phone_usage", True).valid


@pytest.mark.parametrize("label", ["4 .5 .5 .2 .2", "0 nan .5 .2 .2", "0 .9 .5 .5 .2", "0 .5 .5 -.2 .2", "0 .5 .5"])
def test_invalid_labels(data, label):
    (data / "labels/train/train_0_0.txt").write_text(label)
    assert not validate(data, "phone_usage", True).valid


def test_missing_label_and_corrupt_media(data):
    (data / "labels/train/train_0_0.txt").unlink()
    (data / "images/test/test_0_0.jpg").write_bytes(b"invalid image")
    result = validate(data, "phone_usage", True)
    assert not result.valid
    assert any("Missing annotation" in e for e in result.errors)


def test_source_leakage(data):
    path = data / "manifest.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[-1]["source_id"] = rows[0]["source_id"]
    path.write_text("\n".join(map(json.dumps, rows)))
    assert any("leaks" in e for e in validate(data, "phone_usage", True).errors)


def test_exact_duplicate(data):
    shutil.copyfile(data / "images/train/train_0_0.jpg", data / "images/test/test_0_0.jpg")
    assert any("Exact duplicate" in e for e in validate(data, "phone_usage", True).errors)


def test_synthetic_requires_opt_in(data):
    assert not validate(data, "phone_usage").valid


def test_yolo_boundary_rounding_is_valid_but_real_overflow_is_not():
    assert valid_yolo_box(0.03320312, 0.34236111, 0.06640625, 0.13194444)
    assert not valid_yolo_box(0.9, 0.5, 0.5, 0.2)


def test_hidden_cigarette_is_restricted_to_smoking_events():
    record = {
        "source_id": "source",
        "group_id": "group",
        "events": [
            {
                "subtype": "phone_usage",
                "start": 1.0,
                "end": 2.0,
                "box": [0.1, 0.1, 0.5, 0.8],
                "hidden_cigarette": False,
            }
        ],
    }
    with pytest.raises(ValueError, match="only for smoking"):
        validate_event_record(record, 3.0, ["phone_usage"])
    record["events"][0]["subtype"] = "smoking"
    validate_event_record(record, 3.0, ["smoking"], allow_hidden_cigarette=True)


def test_graph_rejects_orphan(tmp_path):
    from tools.build_context_graph import build

    (tmp_path / "INDEX.md").write_text("---\nid: index\ntype: index\nstatus: active\nlinks: []\n---\n")
    (tmp_path / "orphan.md").write_text("---\nid: orphan\ntype: component\nstatus: active\nlinks: []\n---\n")
    with pytest.raises(ValueError, match="Orphan"):
        build(tmp_path)
