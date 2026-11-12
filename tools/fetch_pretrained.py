"""Download explicitly selected registered pretrained assets with SHA-256 verification."""

from __future__ import annotations
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from training.common.assets import fetch


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="+")
    args = parser.parse_args()
    try:
        for name in args.names:
            print(fetch(name))
    except (ValueError, KeyError, OSError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
