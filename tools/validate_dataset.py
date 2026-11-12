"""Validate one task or audit all supplied datasets without modifying them."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from safesight.config import ROOT, resolve_path
from safesight.contracts import SLUGS
from training.common.datasets import audit_cross_dataset, validate
from training.common.splitting import materialize_splits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug", choices=[*SLUGS, "all"])
    parser.add_argument("--root", help="Dataset root for one task; parent root for all")
    parser.add_argument("--allow-synthetic", action="store_true")
    parser.add_argument("--seed", type=int, default=42, help="Match the training seed for automatic source-group splits")
    args = parser.parse_args()
    slugs = SLUGS if args.slug == "all" else [args.slug]
    roots = {
        slug: resolve_path(args.root) / slug
        if args.slug == "all" and args.root
        else resolve_path(args.root)
        if args.root
        else ROOT / "datasets" / slug
        for slug in slugs
    }
    failed = False
    for slug, root in roots.items():
        root = materialize_splits(root, slug, args.seed)
        roots[slug] = root
        result = validate(root, slug, args.allow_synthetic)
        result.write(ROOT / "artifacts/reports/validation" / slug)
        print(f"{slug}: {'VALID' if result.valid else 'INVALID'}; {len(result.warnings)} warnings")
        for error in result.errors:
            print(f"  ERROR: {error}")
        failed |= not result.valid
    if args.slug == "all":
        for error in audit_cross_dataset(roots):
            print(f"  LEAKAGE: {error}")
            failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
