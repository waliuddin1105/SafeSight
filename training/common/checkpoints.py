"""Restore complete classifier state for resume and memory-failure rollback."""

import random

import numpy as np
import torch


def restore_state(network, optimizer, scheduler, checkpoint: dict) -> None:
    """Restore learned/optimizer/scheduler state and all participating RNG streams."""
    network.load_state_dict(checkpoint["model"])
    optimizer.load_state_dict(checkpoint["optimizer"])
    scheduler.load_state_dict(checkpoint["scheduler"])
    random.setstate(checkpoint["python_rng"])
    np.random.set_state(checkpoint["numpy_rng"])
    torch.set_rng_state(checkpoint["torch_rng"].cpu())
    if torch.cuda.is_available() and checkpoint.get("cuda_rng"):
        torch.cuda.set_rng_state_all(checkpoint["cuda_rng"])
