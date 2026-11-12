"""SafeSight industrial safety monitoring."""

import os
from pathlib import Path

# Keep third-party configuration/cache writes in the configured project workspace.
library_config = Path(
    os.getenv("YOLO_CONFIG_DIR", str(Path(__file__).resolve().parents[1] / "artifacts/library-config"))
)
library_config.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("YOLO_CONFIG_DIR", str(library_config))
