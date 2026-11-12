"""Download/prepare public datasets on the training machine; never start training."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
import yaml

from safesight.config import ROOT, read_yaml, resolve_path
from training.common.dataset_preparation import prepare, write_json

TASKS = ("body_state", "phone_usage", "cigarette_smoking", "fire_smoke")


def main(argv: list[str] | None = None) -> int:
    """Prepare one/all four tasks, preserving data and reporting blocked sources."""
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug", nargs="?", choices=[*TASKS, "all"], default="all")
    parser.add_argument("--config", default="configs/dataset_sources.yaml")
    parser.add_argument("--datasets-root", default=os.getenv("DATASETS_ROOT", "datasets"))
    parser.add_argument("--cache-root", help="Optional archive cache on another disk")
    parser.add_argument(
        "--archive",
        action="append",
        default=[],
        metavar="SLUG=PATH",
        help="Use an already authorized ZIP/TAR export or a complete reviewed SafeSight bundle",
    )
    parser.add_argument(
        "--plan", action="store_true", help="Show sources/requirements without network access or dataset writes"
    )
    args = parser.parse_args(argv)
    config = read_yaml(args.config)
    if config.get("schema_version") != 1:
        parser.error("Unsupported dataset source configuration version")
    roots = resolve_path(args.datasets_root)
    cache = resolve_path(args.cache_root) if args.cache_root else roots / "_downloads"
    local = {}
    for entry in args.archive:
        slug, separator, value = entry.partition("=")
        if not separator or slug not in TASKS or not value:
            parser.error("--archive must be SLUG=PATH for one of the four supported tasks")
        local[slug] = resolve_path(value)
    selected = TASKS if args.slug == "all" else [args.slug]
    if args.plan:
        for slug in selected:
            source = config["sources"][slug]
            print(f"{slug}: {source['title']} -> {roots / slug}")
            print(f"  Source: {source['publisher']}")
            for gap in source["annotation_gaps"]:
                print(f"  Requires: {gap}")
        print("Guard verification excluded. No downloads or training performed.")
        return 0
    report = {"training_executed": False, "datasets_root": str(roots), "datasets": {}}
    for slug in selected:
        source = config["sources"][slug]
        print(f"Preparing {slug} ...", flush=True)
        try:
            result = prepare(
                source,
                slug,
                roots,
                cache,
                int(config["minimum_free_gb"] * 1024**3),
                int(config["maximum_extracted_gb"] * 1024**3),
                local.get(slug),
            )
            if result["status"] == "READY":
                train_config = read_yaml(f"training/{slug}/config.yaml")
                train_config["dataset"] = str(roots / slug)
                path = ROOT / "artifacts/dataset-preparation" / f"{slug}.yaml"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(yaml.safe_dump(train_config, sort_keys=False), encoding="utf-8")
                result["training_command"] = (
                    f"python training/{slug}/train.py --config artifacts/dataset-preparation/{slug}.yaml"
                )
        except Exception as error:
            # Provider URLs may contain credentials; persist only sanitized errors.
            from urllib.error import URLError

            message = (
                "Network request failed; check access/connectivity or provide --archive"
                if isinstance(error, URLError)
                else str(error)
            )
            for key in (
                "ROBOFLOW_API_KEY",
                "KAGGLE_KEY",
                "POLAR_ARCHIVE_URL",
                "FPI_DET_ARCHIVE_URL",
                "SMOKING_ARCHIVE_URL",
                "DFIRE_ARCHIVE_URL",
            ):
                value = os.getenv(key)
                if value:
                    message = message.replace(value, "[redacted]")
            result = {"slug": slug, "status": "BLOCKED", "reason": message}
        report["datasets"][slug] = result
        print(f"  {result['status']}")
        for note in result.get("next_steps", []):
            print(f"  {note}")
        if result.get("reason"):
            print("  " + result["reason"])
        if result.get("training_command"):
            print("  Ready command: " + result["training_command"])
    path = ROOT / "artifacts/dataset-preparation/report.json"
    write_json(path, report)
    print(f"Readiness report: {path}")
    print("No training was performed. READY describes dataset structure, not measured model quality.")
    return 0 if all(row["status"] == "READY" for row in report["datasets"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
