"""Portable project configuration and safe path resolution."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def resolve_path(value: str | Path, base: Path = ROOT) -> Path:
    """Resolve a configured path independently of the working directory."""
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def within(root: Path, relative: str | Path) -> Path:
    """Reject path traversal, including symlinks escaping the storage root."""
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Path escapes its configured root")
    return path


def read_yaml(path: str | Path) -> dict[str, Any]:
    """Read a YAML mapping without constructing arbitrary objects."""
    with resolve_path(path).open(encoding="utf-8") as handle:
        result = yaml.safe_load(handle)
    if not isinstance(result, dict):
        raise ValueError(f"Expected a YAML mapping: {path}")
    return result


def settings() -> dict[str, Any]:
    """Load environment overrides without changing existing environment values."""
    load_dotenv(ROOT / ".env")
    value = read_yaml(os.getenv("SAFESIGHT_CONFIG", "configs/application.yaml"))
    for key in ("models_root", "media_root"):
        value[key] = resolve_path(os.getenv(key.upper(), value[key]))
    value["database_url"] = os.getenv(
        "DATABASE_URL", "postgresql+psycopg://safesight:safesight@localhost:5432/safesight"
    )
    value["secret_key"] = os.getenv("SECRET_KEY", "")
    value["evaluation_mode"] = os.getenv("EVALUATION_MODE", str(value["evaluation_mode"])).lower() == "true"
    return value
