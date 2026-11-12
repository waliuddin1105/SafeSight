"""Non-training checks for dataset stages, staging and frozen representations."""

import json
import shutil

import torch

from training.common.datasets import jsonl, validate
from training.common.features import FeatureDataset, FeatureWriter, accumulation_weight
from training.common.fixtures import generate
from training.common.runner import stage_yolo


def test_images_train_without_events_and_hash_is_independent(tmp_path):
    root = shutil.copytree(generate("phone_usage"), tmp_path / "images")
    before = validate(root, "phone_usage", True, qualification=False)
    shutil.rmtree(root / "events")
    shutil.rmtree(root / "videos")
    after = validate(root, "phone_usage", True, qualification=False)
    assert before.valid and after.valid
    assert before.dataset_hash == after.dataset_hash
    assert not validate(root, "phone_usage", True, qualification=True).valid


def test_yolo_staging_preserves_duplicate_stems(tmp_path):
    root = shutil.copytree(generate("phone_usage"), tmp_path / "source")
    rows = jsonl(root / "manifest.jsonl")
    for n, row in enumerate(rows):
        for field, folder, suffix in (("path", "images", ".jpg"), ("annotation", "labels", ".txt")):
            old = root / row[field]
            name = f"{folder}/{row['split']}/{n}/same{suffix}"
            new = root / name
            new.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(old, new)
            row[field] = name
    (root / "manifest.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    staged = tmp_path / "stage"
    stage_yolo(root, staged, "phone_usage")
    for split in ("val", "test"):
        assert len(list((staged / "images" / split).glob("*"))) == sum(r["split"] == split for r in rows)


def test_disk_features_and_exact_accumulation_weights(tmp_path):
    writer = FeatureWriter(tmp_path, "train")
    sample = (torch.ones(33, 4), torch.tensor(2), torch.tensor(1))
    writer.append(sample)
    dataset = FeatureDataset(tmp_path, writer.rows)
    assert len(dataset) == 1 and dataset.labels.tolist() == [2]
    assert torch.equal(dataset[0][0], sample[0])
    # Batches 4,4,4,2 with accumulation=3: first update uses 12, last uses 2.
    assert [accumulation_weight(i, 4, 4, 14, 3) for i in range(4)] == [1 / 3, 1 / 3, 1 / 3, 1.0]


def test_failure_gallery_uses_measured_examples(tmp_path):
    from training.common.reports import failure_gallery, dataset_inventory
    root = generate("phone_usage")
    inventory = dataset_inventory(root, "phone_usage")
    assert inventory["class_instances"]["phone"] > 0
    output = tmp_path / "gallery"
    failure_gallery(root, output, [{"video": "videos/test/evaluation_0.mp4", "timestamp": 0, "subtype": "phone_usage", "kind": "false_negative"}])
    assert (output / "failure_0.jpg").exists()
    assert "false_negative" in (output / "index.html").read_text()
