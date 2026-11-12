"""Verify supported Python, imports, CPU operations, and optional CUDA capability."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
importlib.import_module("safesight")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training-only", action="store_true")
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError("Supported Python version is 3.11")
    modules = [
        "torch",
        "torchvision",
        "ultralytics",
        "mediapipe",
        "cv2",
        "numpy",
        "sklearn",
        "PIL",
        "yaml",
        "av",
        "dotenv",
    ]
    if not args.training_only:
        modules += ["flask", "sqlalchemy", "alembic", "psycopg", "waitress", "pydantic"]
    for name in modules:
        importlib.import_module(name)
    import torch
    import torchvision
    import mediapipe as mp

    assert hasattr(mp.tasks.vision, "PoseLandmarker")
    assert torchvision.ops.nms(torch.tensor([[0.0, 0.0, 1.0, 1.0]]), torch.tensor([0.9]), 0.5).numel() == 1
    result = {
        "python": sys.version,
        "imports": modules,
        "cpu_operation": (torch.ones(2, 2) @ torch.ones(2, 2)).tolist(),
        "cuda_available": torch.cuda.is_available(),
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
