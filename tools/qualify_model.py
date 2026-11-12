"""Qualify a frozen model using labeled validation/test recordings; never train."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from safesight.config import read_yaml, resolve_path, within
from safesight.contracts import SLUGS
from training.common.runner import qualify_version
from training.common.splitting import materialize_splits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug", choices=SLUGS)
    parser.add_argument("run_id")
    parser.add_argument("--config")
    args = parser.parse_args()
    config = read_yaml(args.config or f"training/{args.slug}/config.yaml")
    if config["slug"] != args.slug:
        raise ValueError("Config slug differs from selected model")
    version = within(resolve_path(config["output_root"]), f"{args.slug}/versions/{args.run_id}")
    saved = json.loads((version / "training_config.json").read_text())
    # Reuse training preprocessing and split assignment; only input location moves.
    saved["dataset"] = config["dataset"]
    saved["pretrained_root"] = str(version.parents[2] / "_pretrained")
    dataset = materialize_splits(resolve_path(saved["dataset"]), args.slug, saved["seed"], tuple(saved["split_ratios"]))
    return qualify_version(args.slug, version, dataset, saved)


if __name__ == "__main__":
    raise SystemExit(main())
