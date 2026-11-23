"""Focused contracts for curated fire/smoke dataset preparation."""

from pathlib import Path
import zipfile

from PIL import Image
import pytest

from tools.prepare_fire_smoke_curated import (
    Box,
    audit_boxes,
    dhash,
    parse_labels,
    roboflow_export_endpoint,
    safe_extract,
    scene_group,
    visually_near,
)


def test_class_mapping_drops_other_and_preserves_negative(tmp_path: Path):
    label = tmp_path / "sample.txt"
    label.write_text("0 0.5 0.5 0.2 0.2\n1 0.5 0.5 0.4 0.4\n2 0.5 0.5 0.1 0.1\n")
    boxes, ignored = parse_labels(
        label,
        ["smoke", "fire", "other"],
        {"smoke": "smoke", "fire": "fire", "other": "other"},
    )
    assert [box.class_id for box in boxes] == [0, 1]
    assert ignored == 1


def test_invalid_and_full_frame_annotations_are_not_silently_accepted(tmp_path: Path):
    invalid = tmp_path / "invalid.txt"
    invalid.write_text("0 0.95 0.5 0.2 0.2\n")
    with pytest.raises(ValueError, match="outside"):
        parse_labels(invalid, ["smoke", "fire"], {"smoke": "smoke", "fire": "fire"})
    assert audit_boxes([Box(0, 0.5, 0.5, 0.95, 0.95)]) == ["smoke_box_area_over_0.8"]


def test_scene_group_removes_export_hash_and_frame_number():
    assert scene_group("source", "camera-a-frame00120_jpg.rf.abc123") == "source:camera-a"


def test_dhash_is_stable_for_same_pixels():
    image = Image.new("RGB", (32, 32), "red")
    assert dhash(image) == dhash(image.copy())


def test_perceptual_candidate_requires_pixel_similarity(tmp_path: Path):
    first, second = tmp_path / "first.png", tmp_path / "second.png"
    Image.new("RGB", (32, 32), "red").save(first)
    Image.new("RGB", (32, 32), "blue").save(second)
    assert not visually_near(first, second)


def test_zip_path_traversal_is_rejected(tmp_path: Path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../escape.txt", "bad")
    with pytest.raises(ValueError, match="Unsafe"):
        safe_extract(archive, tmp_path / "extract")


def test_roboflow_endpoint_uses_workspace_without_credentials():
    endpoint = roboflow_export_endpoint(
        {"workspace": "example-workspace", "project": "example-project", "version": 3}
    )
    assert endpoint == "https://api.roboflow.com/example-workspace/example-project/3/yolov8"
    assert "api_key" not in endpoint
