"""Generate synthetic execution fixtures exclusively under tests/fixtures."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from safesight.contracts import SLUGS
from training.common.fixtures import generate

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug", nargs="?", choices=[*SLUGS, "all"], default="all")
    args = parser.parse_args()
    for slug in SLUGS if args.slug == "all" else [args.slug]:
        print(generate(slug))
