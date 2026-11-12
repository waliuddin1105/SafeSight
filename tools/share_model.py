"""Export or fetch immutable model versions through a shared drive or HTTPS."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from safesight.config import resolve_path, settings, within
from safesight.contracts import CLASSES, SLUGS
from safesight.model_loaders.registry import ModelCard
from training.common.dataset_preparation import extract, file_hash, open_url


def checked_card(root: Path, slug: str, run_id: str) -> tuple[Path, ModelCard]:
    """Check metadata and bytes without loading or executing model weights."""
    if slug not in SLUGS or not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        raise ValueError("Invalid model slug or run ID")
    version = within(root, f"{slug}/versions/{run_id}")
    card = ModelCard.model_validate_json((version / "model_card.json").read_text(encoding="utf-8"))
    artifact = within(root, card.artifact)
    if (
        card.slug != slug
        or card.run_id != run_id
        or card.classes != CLASSES[slug]
        or card.schema_version != 1
        or card.preprocessing != "v1"
        or not artifact.is_relative_to(version)
        or artifact.name == "model_card.json"
    ):
        raise ValueError("Incompatible card or artifact outside the selected version")
    if file_hash(artifact) != card.sha256:
        raise ValueError("Model artifact checksum mismatch")
    return artifact, card


def export_model(root: Path, slug: str, run_id: str, output: Path) -> str:
    """Create a portable weights/card bundle and a SHA-256 sidecar."""
    artifact, _ = checked_card(root, slug, run_id)
    card = root / slug / "versions" / run_id / "model_card.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    sidecar = output.with_suffix(output.suffix + ".sha256")
    if output.exists() or sidecar.exists():
        raise ValueError("Export destination already exists; choose a new name")
    files = {p.relative_to(root).as_posix(): file_hash(p) for p in (artifact, card)}
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_STORED) as archive:
        for name in files:
            archive.write(within(root, name), name)
        archive.writestr(
            "bundle.json", json.dumps({"schema_version": 1, "slug": slug, "run_id": run_id, "files": files})
        )
    checksum = file_hash(output)
    sidecar.write_text(checksum + "\n", encoding="utf-8")
    return checksum


def fetch_model(root: Path, source: str, checksum: str) -> Path:
    """Verify/download a bundle and atomically install an inactive model version."""
    if not re.fullmatch(r"[a-fA-F0-9]{64}", checksum):
        raise ValueError("Provide the bundle's 64-character SHA-256 from the exporter")
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".model-transfer-", dir=root) as temporary:
        staging = Path(temporary)
        archive = staging / "bundle.zip"
        if source.startswith("https://"):
            with open_url(source) as response, archive.open("wb") as handle:
                shutil.copyfileobj(response, handle, 1024 * 1024)
        else:
            shutil.copyfile(resolve_path(source), archive)
        if file_hash(archive) != checksum.lower():
            raise ValueError("Bundle checksum mismatch; nothing installed")
        extracted = staging / "contents"
        extract(archive, extracted, reserve=0, maximum=20 * 1024**3)
        bundle = json.loads((extracted / "bundle.json").read_text(encoding="utf-8"))
        if bundle["schema_version"] != 1:
            raise ValueError("Unsupported bundle schema")
        slug, run_id = bundle["slug"], bundle["run_id"]
        artifact, _ = checked_card(extracted, slug, run_id)
        expected = {artifact.relative_to(extracted).as_posix(), f"{slug}/versions/{run_id}/model_card.json"}
        if set(bundle["files"]) != expected:
            raise ValueError("Bundle must contain exactly the selected weights and card")
        actual = {p.relative_to(extracted).as_posix() for p in extracted.rglob("*") if p.is_file()}
        if actual != expected | {"bundle.json", ".extracted.json"}:
            raise ValueError("Unexpected files in model bundle")
        for name, digest in bundle["files"].items():
            if file_hash(within(extracted, name)) != digest:
                raise ValueError("Bundled file checksum mismatch")
        destination = within(root, f"{slug}/versions/{run_id}")
        if destination.exists():
            for name, digest in bundle["files"].items():
                if file_hash(within(root, name)) != digest:
                    raise ValueError("Existing version differs; refusing to overwrite")
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        (extracted / slug / "versions" / run_id).rename(destination)
        return destination


def main() -> int:
    """Share versions explicitly; activation remains a separate quality-aware action."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-root", default=str(settings()["models_root"]))
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("slug", choices=SLUGS)
    export.add_argument("run_id")
    export.add_argument("--output", required=True)
    fetch = commands.add_parser("fetch")
    fetch.add_argument("source", help="Shared-drive ZIP path or direct HTTPS download URL")
    fetch.add_argument("--sha256", required=True)
    args = parser.parse_args()
    root = resolve_path(args.models_root)
    if args.command == "export":
        print("Bundle SHA-256: " + export_model(root, args.slug, args.run_id, resolve_path(args.output)))
    else:
        print("Installed inactive version: " + str(fetch_model(root, args.source, args.sha256)))
        print("Activate with tools/activate_model.py after reviewing its model card.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
