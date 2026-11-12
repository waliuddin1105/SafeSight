"""Timestamp-preserving video decoding and browser-compatible evidence encoding."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path
from fractions import Fraction

import av
import numpy as np


def frames(path: Path, fps: float = 5) -> Iterator[tuple[float, np.ndarray]]:
    """Yield sampled RGB frames using presentation timestamps."""
    next_time = 0.0
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        native_fps = float(stream.average_rate or fps)
        origin = None
        for index, frame in enumerate(container.decode(stream)):
            timestamp = float(frame.time if frame.time is not None else index / native_fps)
            if origin is None:
                origin = timestamp
            timestamp -= origin
            if timestamp + 1e-6 >= next_time:
                yield timestamp, frame.to_ndarray(format="rgb24")
                next_time = timestamp + 1 / fps


def write_video(
    path: Path, images: Iterable[np.ndarray], fps: int = 5, timestamps: Iterable[float] | None = None
) -> None:
    """Encode H.264 MP4 and atomically publish it after flushing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".partial.mp4")
    iterator = iter(images)
    first = next(iterator, None)
    if first is None:
        raise ValueError("Cannot encode an empty clip")
    height, width = first.shape[:2]
    with av.open(str(temporary), "w") as container:
        stream = container.add_stream("libx264", rate=fps)
        stream.width, stream.height = width // 2 * 2, height // 2 * 2
        stream.pix_fmt = "yuv420p"
        stream.time_base = Fraction(1, 1000)
        stream.codec_context.time_base = Fraction(1, 1000)
        stream.options = {"crf": "25", "preset": "ultrafast"}
        from itertools import chain

        times = iter(timestamps) if timestamps is not None else None
        origin = None
        previous = -1
        for index, image in enumerate(chain([first], iterator)):
            frame = av.VideoFrame.from_ndarray(image[: stream.height, : stream.width], format="rgb24")
            timestamp = next(times) if times is not None else index / fps
            if origin is None:
                origin = timestamp
            position = round((timestamp - origin) * 1000)
            if position <= previous:
                raise ValueError("Evidence timestamps must increase")
            frame.pts, frame.time_base = position, Fraction(1, 1000)
            previous = position
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    temporary.replace(path)
