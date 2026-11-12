"""Immutable per-recording model selection and inference configuration."""

import hashlib
import json

from safesight.config import read_yaml, within
from safesight.contracts import SLUGS
from safesight.model_loaders.registry import ModelCard


def snapshot_models(config: dict, selected: list[str], evaluation: bool, versions: dict | None = None) -> dict:
    """Capture existing cards and hashes; never activate or download models."""
    if not selected or len(set(selected)) != len(selected) or any(s not in SLUGS for s in selected):
        raise ValueError("Choose one or more unique supported models")
    if versions is not None and not isinstance(versions, dict):
        raise ValueError("versions must map model slugs to version IDs")
    cards = {}
    card_hashes = {}
    for slug in selected:
        chosen = (versions or {}).get(slug)
        if chosen == "":
            chosen = None
        if chosen is not None and (
            not isinstance(chosen, str) or not chosen.replace("_", "").replace("-", "").isalnum()
        ):
            raise ValueError("Invalid model version ID")
        path = within(
            config["models_root"], f"{slug}/versions/{chosen}/model_card.json" if chosen else f"{slug}/model_card.json"
        )
        if chosen and not path.exists():
            active = within(config["models_root"], f"{slug}/model_card.json")
            active_card = ModelCard.model_validate_json(active.read_bytes())
            if active_card.run_id != chosen:
                raise ValueError("Requested model version is unavailable")
            path = active
        raw = path.read_bytes()
        card = ModelCard.model_validate_json(raw)
        card_hashes[slug] = hashlib.sha256(raw).hexdigest()
        if card.slug != slug:
            raise ValueError("Model slug differs from selected use case")
        if (card.synthetic or card.quality.get("status") != "PASS") and not evaluation:
            raise ValueError("Select evaluation testing explicitly for unqualified models")
        artifact = within(config["models_root"], card.artifact)
        # Stream large files rather than retaining weights in API memory.
        digest = hashlib.sha256()
        with artifact.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != card.sha256:
            raise ValueError("Selected model artifact checksum mismatch")
        cards[slug] = card.model_dump()
    value = {
        "cards": cards,
        "evaluation": evaluation,
        "policy": read_yaml(config["inference_config"]),
        "sample_fps": config["sample_fps"],
    }
    fusion = within(config["models_root"], "fusion_card.json")
    if fusion.exists():
        qualified = json.loads(fusion.read_text())
        if qualified.get("status") == "PASS" and qualified.get("models") == {
            s: card_hashes.get(s) for s in ("cigarette_smoking", "fire_smoke")
        }:
            value["fusion"] = qualified
    value["fingerprint"] = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    return value
