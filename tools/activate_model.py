"""Select a versioned model without editing pipeline code."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from safesight.config import settings, within
from safesight.contracts import SLUGS
from safesight.contracts.model_card import (
    DeploymentPointer,
    ModelCard,
    QualificationAttestation,
    contract_sha256,
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug", choices=SLUGS)
    parser.add_argument("run_id")
    parser.add_argument("--evaluation", action="store_true")
    args = parser.parse_args()
    root = settings()["models_root"]
    card_path = within(root, f"{args.slug}/versions/{args.run_id}/model_card.json")
    card = ModelCard.model_validate_json(card_path.read_text())
    if card.slug != args.slug:
        raise SystemExit("Model card slug differs from the selected use case")
    if card.schema_version == 2:
        if args.evaluation:
            raise SystemExit("Schema-v2 evaluation versions are selected per testing job, not globally deployed")
        candidates = []
        for path in card_path.parent.glob("qualifications/*/attestation.json"):
            attestation = QualificationAttestation.model_validate_json(path.read_text(encoding="utf-8"))
            if (
                attestation.model_card_sha256 == contract_sha256(card)
                and attestation.quality.get("status") == "PASS"
            ):
                candidates.append((attestation.created_at, path, attestation))
        if not candidates:
            raise SystemExit("No matching PASS qualification exists for this model version")
        _, qualification_path, qualification = max(candidates, key=lambda item: item[0])
        deployment = DeploymentPointer(
            slug=args.slug,
            run_id=card.run_id,
            model_card=card_path.relative_to(root).as_posix(),
            model_card_sha256=contract_sha256(card),
            qualification=qualification_path.relative_to(root).as_posix(),
            qualification_sha256=contract_sha256(qualification),
            activated_at=datetime.now(timezone.utc).isoformat(),
        )
        target = within(root, f"{args.slug}/deployment.json")
        temporary = target.with_suffix(".tmp")
        temporary.write_text(deployment.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(target)
        print("Selected qualified deployment; restart the worker to reload")
        raise SystemExit(0)
    if (card.synthetic or card.quality["status"] != "PASS") and not args.evaluation:
        raise SystemExit("Unqualified artifact requires --evaluation and EVALUATION_MODE=true at runtime")
    target = within(root, f"{args.slug}/model_card.json")
    target.write_text(card.model_dump_json(indent=2))
    print("Selected model; restart the worker to reload")
