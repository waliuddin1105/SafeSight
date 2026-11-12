"""Measure inference throughput on identified hardware without training or accuracy claims."""

import argparse
import json
from pathlib import Path
import platform
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import torch
import psutil
from safesight.config import ROOT, settings, read_yaml
from safesight.model_loaders.registry import Registry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", action="store_true", help="Explicit untrained synthetic models")
    parser.add_argument("--frames", type=int, default=10)
    parser.add_argument("--evaluation", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.frames <= 10000:
        parser.error("frames must be between 1 and 10000")
    cfg = settings()
    root = cfg["models_root"]
    if args.fixtures:
        from tools.generate_inference_fixtures import generate

        root = generate()
    registry = Registry(root, evaluation=args.fixtures or args.evaluation)
    timings = []
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    try:
        if not registry.adapters:
            raise ValueError("No compatible models available for benchmarking")
        for i in range(args.frames):
            start = time.perf_counter()
            if registry.pose:
                registry.pose.extract(image)
            for adapter in registry.adapters.values():
                adapter.predict(image, i / cfg["sample_fps"])
            timings.append(time.perf_counter() - start)
    finally:
        registry.close()
    fps = len(timings) / sum(timings)
    policy = read_yaml(cfg["inference_config"])
    result = {
        "os": platform.system(),
        "architecture": platform.machine(),
        "processor": platform.processor(),
        "logical_cpus": psutil.cpu_count(),
        "memory_bytes": psutil.virtual_memory().total,
        "python": platform.python_version(),
        "torch": torch.__version__,
        "device": registry.device,
        "frames": args.frames,
        "synthetic_untrained": args.fixtures,
        "input": [640, 480],
        "average_fps": fps,
        "p95_frame_seconds": float(np.quantile(timings, 0.95)),
        "target_fps": cfg["sample_fps"],
        "target_sustained": fps >= cfg["sample_fps"],
        "resident_bytes": psutil.Process().memory_info().rss,
        "guard_window_filled": args.frames
        >= policy["entrance_guard"]["fps"] * policy["entrance_guard"]["window_seconds"],
        "limits": "Blank synthetic input; no accuracy or real-camera throughput claim. Detector fixtures are smaller than production defaults.",
    }
    output = ROOT / "artifacts/reports/benchmark.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
