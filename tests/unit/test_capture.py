"""Exercise bounded native input in a subprocess using generated video only."""

from safesight.ingestion.capture import CaptureReader
from training.common.fixtures import generate


def test_native_reader_decodes_fixture_and_releases_process():
    video = generate("phone_usage") / "videos/test/evaluation_0.mp4"
    reader = CaptureReader(str(video), fps=5, timeout=10)
    try:
        ok, frame = reader.read()
        assert ok and frame.ndim == 3
    finally:
        reader.release()
    assert not reader.process.is_alive()
