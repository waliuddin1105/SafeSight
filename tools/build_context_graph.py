"""Build or check the context graph, rejecting unreachable and broken nodes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import yaml  # noqa: E402


def build(root: Path) -> dict:
    """Parse all markdown frontmatter and enforce reachability from index."""
    nodes = {}
    for path in sorted(root.rglob("*.md")):
        content = path.read_text(encoding="utf-8")
        if not content.startswith("---\n"):
            raise ValueError(f"Missing frontmatter: {path}")
        meta = yaml.safe_load(content.split("---", 2)[1])
        if not all(key in meta for key in ("id", "type", "status", "links")) or not isinstance(meta["links"], list):
            raise ValueError(f"Invalid frontmatter: {path}")
        if meta["id"] in nodes:
            raise ValueError(f"Duplicate id: {meta['id']}")
        nodes[meta["id"]] = {**meta, "path": path.relative_to(root).as_posix()}
    if "index" not in nodes:
        raise ValueError("Missing index node")
    for node in nodes.values():
        for target in node["links"]:
            if target not in nodes:
                raise ValueError(f"Broken link: {node['id']} -> {target}")
    reached, queue = set(), ["index"]
    while queue:
        current = queue.pop()
        if current not in reached:
            reached.add(current)
            queue.extend(nodes[current]["links"])
    if reached != set(nodes):
        raise ValueError(f"Orphan nodes: {sorted(set(nodes) - reached)}")
    return {
        "schema_version": 1,
        "nodes": list(nodes.values()),
        "edges": [{"from": n["id"], "to": t} for n in nodes.values() for t in n["links"]],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        result = json.dumps(build(ROOT / "ai-context"), indent=2) + "\n"
        path = ROOT / "ai-context/graph.json"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != result:
                raise ValueError("Context graph is stale; run this command without --check")
        else:
            path.write_text(result, encoding="utf-8")
        print("Context graph OK")
        return 0
    except (ValueError, KeyError, yaml.YAMLError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
