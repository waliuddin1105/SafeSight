"""Runtime split tests; no training entrypoint is executed."""

import json
from pathlib import Path

import pytest

from training.common.splitting import materialize_splits, split_for_group
from training.common.datasets import sha256


def flat_dataset(root):
    """Small source-group fixture without image decoding or model execution."""
    root.mkdir()
    records = []
    for i in range(30):
        for j in range(2):
            name = f"g{i}_{j}"
            media = root / "images" / f"{name}.jpg"
            annotation = root / "annotations" / f"{name}.json"
            media.parent.mkdir(exist_ok=True)
            annotation.parent.mkdir(exist_ok=True)
            media.write_bytes(f"fixture-{name}".encode())
            annotation.write_text('{"people": []}')
            records.append(
                dict(
                    sample_id=name,
                    path=f"images/{name}.jpg",
                    annotation=f"annotations/{name}.json",
                    source_id=f"video{i}",
                    group_id=f"session{i}",
                    start=j,
                    end=j,
                )
            )
    (root / "manifest.jsonl").write_text("".join(json.dumps(row) + "\n" for row in records))
    return records


def test_runtime_splits_preserve_sources_and_are_reproducible(tmp_path):
    root = tmp_path / "original"
    rows = flat_dataset(root)
    before = {str(p): sha256(p) for p in root.rglob("*") if p.is_file()}
    output = materialize_splits(root, "body_state", output_root=tmp_path / "staged")
    staged = [json.loads(line) for line in (output / "manifest.jsonl").read_text().splitlines()]
    assert {r["split"] for r in staged} == {"train", "val", "test"}
    for row in staged:
        assert row["split"] == split_for_group(row["group_id"])
        assert (output / row["path"]).is_file()
    assert before == {str(p): sha256(p) for p in root.rglob("*") if p.is_file()}
    assert materialize_splits(root, "body_state", output_root=tmp_path / "staged") == output
    (root / "manifest.jsonl").write_text("".join(json.dumps(row) + "\n" for row in reversed(rows)))
    other = materialize_splits(root, "body_state", output_root=tmp_path / "staged")
    assert (
        json.loads((other / "split_plan.json").read_text())["groups"]
        == json.loads((output / "split_plan.json").read_text())["groups"]
    )


def test_staged_tampering_and_conflicting_source_groups_are_rejected(tmp_path):
    root = tmp_path / "original"
    rows = flat_dataset(root)
    output = materialize_splits(root, "body_state", output_root=tmp_path / "staged")
    next((output / "images").rglob("*.jpg")).write_bytes(b"modified")
    with pytest.raises(ValueError, match="modified"):
        materialize_splits(root, "body_state", output_root=tmp_path / "staged")
    rows[1]["group_id"] = "another-session"
    (root / "manifest.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(ValueError, match="multiple group_ids"):
        materialize_splits(root, "body_state", output_root=tmp_path / "staged")


def test_manual_splits_remain_supported_and_mixed_mode_is_rejected(tmp_path):
    root = tmp_path / "original"
    rows = flat_dataset(root)
    for row in rows:
        row["split"] = "train"
    manifest = root / "manifest.jsonl"
    manifest.write_text("".join(json.dumps(row) + "\n" for row in rows))
    assert materialize_splits(root, "body_state") == root
    rows[0].pop("split")
    manifest.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(ValueError, match="omit split"):
        materialize_splits(root, "body_state")


def test_split_policy_rejects_invalid_ratios_and_shares_task_assignment():
    with pytest.raises(ValueError):
        split_for_group("scene", ratios=(0.8, 0.2, 0.2))
    assert split_for_group("shared-smoking-fire-scene") == split_for_group("shared-smoking-fire-scene")


def test_flat_fixtures_round_trip_through_actual_validator(tmp_path):
    """Exercise image, label and event/video path rewriting with real decoding."""
    import shutil
    from training.common.fixtures import generate
    from training.common.datasets import jsonl, validate

    original = generate("phone_usage")
    root = tmp_path / "flat"
    root.mkdir()
    rows = jsonl(original / "manifest.jsonl")
    groups = {}

    def group(old, split):
        if old not in groups:
            i = 0
            while split_for_group(f"{old}-{i}") != split:
                i += 1
            groups[old] = f"{old}-{i}"
        return groups[old]

    for row in rows:
        split = row.pop("split")
        row["group_id"] = group(row["group_id"], split)
        for key in ("path", "annotation"):
            source = row[key]
            parts = Path(source).parts
            row[key] = Path(parts[0], *parts[2:]).as_posix()
            target = root / row[key]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original / source, target)
    (root / "manifest.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    shutil.copyfile(original / "data.yaml", root / "data.yaml")
    events = []
    for split in ("val", "test"):
        for row in jsonl(original / "events" / f"{split}.jsonl"):
            source = row["video"]
            row["video"] = f"videos/{split}_{Path(source).name}"
            row["group_id"] = group(row["group_id"], split)
            target = root / row["video"]
            target.parent.mkdir(exist_ok=True)
            shutil.copyfile(original / source, target)
            events.append(row)
    (root / "events.jsonl").write_text("".join(json.dumps(r) + "\n" for r in events))
    staged = materialize_splits(root, "phone_usage", output_root=tmp_path / "staged")
    result = validate(staged, "phone_usage", allow_synthetic=True)
    assert result.valid, result.errors
