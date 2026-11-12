"""Independent body_state training entrypoint."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from training.common.runner import cli

if __name__ == "__main__":
    cli("body_state")
