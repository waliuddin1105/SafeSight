"""Compare completed training runs on validation metrics only; never fit a model."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from safesight.config import read_yaml, resolve_path, ROOT
from safesight.contracts import SLUGS, YOLO_SLUGS
from training.common.runner import write_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug", choices=SLUGS)
    parser.add_argument("--fallback-config", action="store_true", help="Write a suggested recipe, not run it")
    args = parser.parse_args()
    config = read_yaml(f"training/{args.slug}/config.yaml")
    output = ROOT / "artifacts/reports/comparisons" / args.slug
    output.mkdir(parents=True, exist_ok=True)
    if args.fallback_config:
        if args.slug in YOLO_SLUGS:
            config["architecture"] = "yolo11n"
        elif args.slug == "body_state":
            config["hidden_sizes"] = [64]
        else:
            config["architecture"] = "resnet18"
        write_json(output / "fallback.yaml", config)
    rows = []
    for path in (resolve_path(config["output_root"]) / args.slug / "versions").glob("*/training_report.json"):
        report = json.loads(path.read_text())
        key = "map50_95" if args.slug in YOLO_SLUGS else "macro_f1"
        value = report.get("validation", {}).get(key)
        if value is not None:
            rows.append(
                {
                    "run_id": path.parent.name,
                    "metric": key,
                    "value": value,
                    "training_dataset_hash": report["dataset_hash"],
                    "synthetic": report["synthetic"],
                }
            )
    hashes = {r["training_dataset_hash"] for r in rows if not r["synthetic"]}
    comparable = len(hashes) == 1
    ranked = (
        sorted([r for r in rows if not r["synthetic"]], key=lambda r: r["value"], reverse=True) if comparable else []
    )
    result = {
        "runs": rows,
        "comparable": comparable,
        "recommended_validation_candidate": ranked[0]["run_id"] if ranked else None,
        "note": "Same split/data required; no test metrics used and no activation performed",
    }
    write_json(output / "comparison.json", result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
