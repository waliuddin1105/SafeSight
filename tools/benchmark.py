"""Measure inference throughput on identified hardware without training or accuracy claims."""

import argparse
import json
from pathlib import Path
import platform
import subprocess
import sys
from threading import Event, Thread
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import torch
import psutil
from safesight.config import ROOT, settings, read_yaml
from safesight.model_loaders.registry import Registry
from safesight.contracts import SLUGS


def monitor_gpu(stop: Event, samples: list[tuple[int, int]]) -> None:
    """Sample NVIDIA compute utilization and used memory without requiring NVML bindings."""
    while not stop.wait(0.2):
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                check=True,
                text=True,
                timeout=2,
            )
            utilization, memory = result.stdout.splitlines()[0].split(",")
            samples.append((int(utilization.strip()), int(memory.strip())))
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            return


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", action="store_true", help="Explicit untrained synthetic models")
    parser.add_argument("--frames", type=int, default=10)
    parser.add_argument("--evaluation", action="store_true")
    parser.add_argument("--model", choices=SLUGS, action="append", help="Benchmark only selected model(s)")
    parser.add_argument("--batch-size", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.frames <= 10000:
        parser.error("frames must be between 1 and 10000")
    if not 1 <= args.batch_size <= 32:
        parser.error("batch-size must be between 1 and 32")
    cfg = settings()
    root = cfg["models_root"]
    if args.fixtures:
        from tools.generate_inference_fixtures import generate

        root = generate()
    selected = {slug: f"{slug}/model_card.json" for slug in args.model} if args.model else None
    registry = Registry(root, evaluation=args.fixtures or args.evaluation, selected=selected)
    timings = []
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    gpu_samples: list[tuple[int, int]] = []
    stop = Event()
    monitor = Thread(target=monitor_gpu, args=(stop, gpu_samples), daemon=True)
    try:
        if not registry.adapters:
            raise ValueError("No compatible models available for benchmarking")
        if registry.device and registry.device.startswith("cuda"):
            monitor.start()
        for start_index in range(0, args.frames, args.batch_size):
            size = min(args.batch_size, args.frames - start_index)
            start = time.perf_counter()
            if registry.pose:
                for _ in range(size):
                    registry.pose.extract(image)
            for adapter in registry.adapters.values():
                timestamps = [(start_index + offset) / cfg["sample_fps"] for offset in range(size)]
                if hasattr(adapter, "predict_batch"):
                    adapter.predict_batch([image] * size, timestamps)
                else:
                    for timestamp in timestamps:
                        adapter.predict(image, timestamp)
            timings.extend([(time.perf_counter() - start) / size] * size)
    finally:
        stop.set()
        if monitor.is_alive():
            monitor.join(timeout=3)
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
        "models": list(registry.cards),
        "frames": args.frames,
        "batch_size": args.batch_size,
        "synthetic_untrained": args.fixtures,
        "input": [640, 480],
        "average_fps": fps,
        "p95_frame_seconds": float(np.quantile(timings, 0.95)),
        "target_fps": cfg["sample_fps"],
        "target_sustained": fps >= cfg["sample_fps"],
        "resident_bytes": psutil.Process().memory_info().rss,
        "gpu_utilization_average_percent": (
            sum(sample[0] for sample in gpu_samples) / len(gpu_samples) if gpu_samples else None
        ),
        "gpu_utilization_max_percent": max((sample[0] for sample in gpu_samples), default=None),
        "gpu_memory_max_mib": max((sample[1] for sample in gpu_samples), default=None),
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
