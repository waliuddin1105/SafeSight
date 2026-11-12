"""Versioned, non-executable serialization for bounded inference recovery state."""

from __future__ import annotations

import base64
from collections import defaultdict, deque
import json
import zlib
from collections.abc import Callable
from typing import Any

import numpy as np

from safesight.contracts import Detection
from safesight.inference.engine import Engine, Temporal, TemporalState, Tracker

TYPES = {cls.__name__: cls for cls in (Engine, Temporal, TemporalState, Tracker, Detection)}


def encode(value: Any, put_blob: Callable[[bytes], str] | None = None) -> Any:
    """Encode only primitives, bounded media arrays and known inference types."""
    if isinstance(value, bytes):
        if put_blob is not None:
            return {"type": "blob", "value": put_blob(value)}
        return {"type": "bytes", "value": base64.b64encode(value).decode()}
    if isinstance(value, np.ndarray):
        if value.dtype != np.uint8:
            raise ValueError("Recovery media must be uint8")
        return {"type": "array", "shape": value.shape, "value": encode(value.tobytes(), put_blob)}
    if isinstance(value, deque):
        return {"type": "deque", "maxlen": value.maxlen, "value": [encode(v, put_blob) for v in value]}
    if isinstance(value, dict):
        return {
            "type": "defaultdict" if isinstance(value, defaultdict) else "dict",
            "value": [[encode(k, put_blob), encode(v, put_blob)] for k, v in value.items()],
        }
    if isinstance(value, (tuple, list)):
        return {"type": "tuple" if isinstance(value, tuple) else "list", "value": [encode(v, put_blob) for v in value]}
    if type(value).__name__ in TYPES and isinstance(value, TYPES[type(value).__name__]):
        return {"type": type(value).__name__, "value": encode(value.__dict__, put_blob)}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError(f"Unsupported recovery state {type(value).__name__}")


def decode(value: Any, get_blob: Callable[[str], bytes] | None = None) -> Any:
    if not isinstance(value, dict):
        return value
    kind, data = value["type"], value["value"]
    if kind == "blob":
        if get_blob is None:
            raise ValueError("Recovery blob store is required")
        return get_blob(data)
    if kind == "bytes":
        return base64.b64decode(data, validate=True)
    if kind == "array":
        return np.frombuffer(decode(data, get_blob), dtype=np.uint8).reshape(value["shape"]).copy()
    if kind in ("dict", "defaultdict"):
        result = {decode(k, get_blob): decode(v, get_blob) for k, v in data}
        return defaultdict(dict, result) if kind == "defaultdict" else result
    if kind in ("list", "tuple", "deque"):
        result = [decode(v, get_blob) for v in data]
        return (
            tuple(result) if kind == "tuple" else deque(result, maxlen=value["maxlen"]) if kind == "deque" else result
        )
    if kind in TYPES:
        result = TYPES[kind].__new__(TYPES[kind])
        result.__dict__.update(decode(data, get_blob))
        return result
    raise ValueError(f"Unknown recovery type {kind}")


def dumps(value: Any, put_blob: Callable[[bytes], str] | None = None) -> bytes:
    return zlib.compress(json.dumps({"version": 1, "state": encode(value, put_blob)}, allow_nan=False).encode())


def loads(payload: bytes, get_blob: Callable[[str], bytes] | None = None) -> Any:
    value = json.loads(zlib.decompress(payload))
    if value["version"] != 1:
        raise ValueError("Unsupported recovery snapshot version")
    return decode(value["state"], get_blob)


def blob_references(payload: bytes) -> set[str]:
    """Read only reference identifiers, without constructing inference objects."""
    found = set()

    def walk(value):
        if isinstance(value, dict):
            if value.get("type") == "blob":
                found.add(value["value"])
            else:
                for item in value.values():
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(json.loads(zlib.decompress(payload)))
    return found
