"""Source identity for reports without assuming a clean or Git-managed checkout."""

from __future__ import annotations

import hashlib
import subprocess

from safesight.config import ROOT


def source_identity() -> dict:
    """Record both committed revision and the actual Python source content."""
    try:
        command = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
        revision = command.stdout.strip() if command.returncode == 0 else None
    except OSError:
        revision = None
    digest = hashlib.sha256()
    for directory in ("safesight", "training", "tools"):
        for path in sorted((ROOT / directory).rglob("*.py")):
            digest.update(path.relative_to(ROOT).as_posix().encode())
            digest.update(path.read_bytes())
    return {
        "revision": revision,
        "python_source_sha256": digest.hexdigest(),
    }
