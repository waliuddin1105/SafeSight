"""Select a versioned model without editing pipeline code."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from safesight.config import settings, within
from safesight.contracts import SLUGS
from safesight.model_loaders.registry import ModelCard

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug", choices=SLUGS)
    parser.add_argument("run_id")
    parser.add_argument("--evaluation", action="store_true")
    args = parser.parse_args()
    root = settings()["models_root"]
    card_path = within(root, f"{args.slug}/versions/{args.run_id}/model_card.json")
    card = ModelCard.model_validate_json(card_path.read_text())
    if card.slug != args.slug or ((card.synthetic or card.quality["status"] != "PASS") and not args.evaluation):
        raise SystemExit("Unqualified artifact requires --evaluation and EVALUATION_MODE=true at runtime")
    target = within(root, f"{args.slug}/model_card.json")
    target.write_text(card.model_dump_json(indent=2))
    print("Selected model; restart the worker to reload")
