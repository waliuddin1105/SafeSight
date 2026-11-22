"""Immutable per-recording model selection and inference configuration."""

import hashlib
import json

from safesight.config import read_yaml, within
from safesight.contracts import SLUGS
from safesight.contracts.model_card import (
    DeploymentPointer,
    ModelCard,
    QualificationAttestation,
    contract_sha256,
)


def snapshot_models(config: dict, selected: list[str], evaluation: bool, versions: dict | None = None) -> dict:
    """Capture existing cards and hashes; never activate or download models."""
    if not selected or len(set(selected)) != len(selected) or any(s not in SLUGS for s in selected):
        raise ValueError("Choose one or more unique supported models")
    if versions is not None and not isinstance(versions, dict):
        raise ValueError("versions must map model slugs to version IDs")
    cards = {}
    qualifications = {}
    card_hashes = {}
    for slug in selected:
        chosen = (versions or {}).get(slug)
        if chosen == "":
            chosen = None
        if chosen is not None and (
            not isinstance(chosen, str) or not chosen.replace("_", "").replace("-", "").isalnum()
        ):
            raise ValueError("Invalid model version ID")
        deployment = None
        deployment_path = within(config["models_root"], f"{slug}/deployment.json")
        if deployment_path.is_file():
            deployment = DeploymentPointer.model_validate_json(deployment_path.read_text(encoding="utf-8"))
            if deployment.slug != slug:
                raise ValueError("Deployment slug differs from selected use case")
        path = within(
            config["models_root"],
            f"{slug}/versions/{chosen}/model_card.json"
            if chosen
            else deployment.model_card
            if deployment
            else f"{slug}/model_card.json",
        )
        if chosen and not path.exists():
            if deployment and deployment.run_id == chosen:
                path = within(config["models_root"], deployment.model_card)
            else:
                active = within(config["models_root"], f"{slug}/model_card.json")
                if not active.is_file() or ModelCard.model_validate_json(active.read_bytes()).run_id != chosen:
                    raise ValueError("Requested model version is unavailable")
                path = active
        card = ModelCard.model_validate_json(path.read_bytes())
        card_hashes[slug] = contract_sha256(card)
        if card.slug != slug:
            raise ValueError("Model slug differs from selected use case")
        qualification = None
        if deployment and deployment.run_id == card.run_id:
            if contract_sha256(card) != deployment.model_card_sha256:
                raise ValueError("Deployed model-card hash mismatch")
            qualification = QualificationAttestation.model_validate_json(
                within(config["models_root"], deployment.qualification).read_text(encoding="utf-8")
            )
            if (
                contract_sha256(qualification) != deployment.qualification_sha256
                or qualification.model_card_sha256 != deployment.model_card_sha256
            ):
                raise ValueError("Deployed qualification hash mismatch")
        effective_quality = qualification.quality if qualification else card.quality
        if card.schema_version == 2 and qualification is None and not evaluation:
            raise ValueError("Selected model has not been qualified")
        if (card.synthetic or effective_quality.get("status") != "PASS") and not evaluation:
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
        if qualification:
            qualifications[slug] = qualification.model_dump()
    value = {
        "cards": cards,
        "qualifications": qualifications,
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
