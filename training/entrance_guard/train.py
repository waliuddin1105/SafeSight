"""Independent entrance_guard training entrypoint."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from training.common.runner import cli

if __name__ == "__main__":
    cli("entrance_guard")
