"""Check M0-M7 source/configuration contracts without importing or running trainers."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import sys

from packaging.requirements import Requirement
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from safesight.contracts import SLUGS  # noqa: E402
from tools.build_context_graph import build  # noqa: E402


def pins(path: Path) -> dict[str, str]:
    result = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "--")):
            continue
        requirement = Requirement(line)
        if not requirement.specifier or any(s.operator != "==" or "*" in s.version for s in requirement.specifier):
            raise ValueError(f"Unpinned requirement: {line}")
        if requirement.marker is None or requirement.marker.evaluate():
            result[requirement.name.lower()] = str(requirement.specifier)
    return result


def check() -> dict:
    root, training = pins(ROOT / "requirements.txt"), pins(ROOT / "training/requirements.txt")
    for name, version in training.items():
        if root.get(name) != version:
            raise ValueError(f"Training/root dependency mismatch: {name}")
    for slug in SLUGS:
        path = ROOT / "training" / slug / "train.py"
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            modules = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            if any(module.startswith("training." + other) for module in modules for other in SLUGS if other != slug):
                raise ValueError(f"Cross-use-case import: {path}")
        config = yaml.safe_load((ROOT / "training" / slug / "config.yaml").read_text())
        if config["slug"] != slug or config["seed"] != 42 or config["quality"]["precision"] < 0.9:
            raise ValueError(f"Invalid training defaults: {slug}")
        if not (ROOT / "datasets" / slug / "README.md").is_file():
            raise ValueError(f"Missing dataset contract: {slug}")
    graph = json.dumps(build(ROOT / "ai-context"), indent=2) + "\n"
    if (ROOT / "ai-context/graph.json").read_text() != graph:
        raise ValueError("Context graph is stale")
    services = yaml.safe_load((ROOT / "compose.yaml").read_text())["services"]
    if set(services) != {"db", "api", "worker", "migrate"}:
        raise ValueError("Incomplete Compose service set")
    for name in ("api", "worker"):
        if not any("models:ro" in mount for mount in services[name]["volumes"]):
            raise ValueError(f"Models must be mounted read-only: {name}")
    return {
        "source_contracts": "PASS",
        "dependency_pins": len(root),
        "independent_trainers": len(SLUGS),
        "training_executed": False,
        "docker_runtime_verified": False,
    }


if __name__ == "__main__":
    print(json.dumps(check(), indent=2))
