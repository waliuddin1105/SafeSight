"""Exportable classifiers whose preprocessing travels with their weights."""

from __future__ import annotations

import torch
from torch import nn


class BodyMLP(nn.Module):
    """Hip-normalized landmarks, visibility, and six joint angles."""

    def __init__(self, classes: int, hidden: list[int], dropout: float):
        super().__init__()
        self.register_buffer("mean", torch.zeros(138))
        self.register_buffer("scale", torch.ones(138))
        layers: list[nn.Module] = []
        previous = 138
        for width in hidden:
            layers.extend([nn.Linear(previous, width), nn.ReLU(), nn.Dropout(dropout)])
            previous = width
        layers.append(nn.Linear(previous, classes))
        self.layers = nn.Sequential(*layers)

    def features(self, points: torch.Tensor) -> torch.Tensor:
        center = (points[:, 23, :3] + points[:, 24, :3]) / 2
        shoulder = (points[:, 11, :3] + points[:, 12, :3]) / 2
        size = torch.linalg.vector_norm(shoulder - center, dim=-1).clamp(min=0.01)
        xyz = ((points[:, :, :3] - center.unsqueeze(1)) / size[:, None, None]).clamp(-10, 10)
        visibility = points[:, :, 3:4].clamp(0, 1)
        normalized = torch.cat([xyz * visibility, visibility], dim=-1).flatten(1)
        angles = []
        for a, b, c in [(11, 13, 15), (12, 14, 16), (11, 23, 25), (12, 24, 26), (23, 25, 27), (24, 26, 28)]:
            first, second = xyz[:, a] - xyz[:, b], xyz[:, c] - xyz[:, b]
            cosine = (first * second).sum(-1) / (
                torch.linalg.vector_norm(first, dim=-1) * torch.linalg.vector_norm(second, dim=-1)
            ).clamp(min=1e-6)
            angles.append(torch.acos(cosine.clamp(-0.99999, 0.99999)) / 3.14159265)
        return torch.cat([normalized, torch.stack(angles, dim=1)], dim=1)

    def forward(self, points: torch.Tensor) -> torch.Tensor:
        return self.layers((self.features(points) - self.mean) / self.scale)


class EntranceLSTM(nn.Module):
    """A frozen visual encoder with a masked sequence classifier."""

    def __init__(self, encoder: nn.Module, feature_size: int, classes: int, dropout: float):
        super().__init__()
        self.encoder = encoder
        for parameter in encoder.parameters():
            parameter.requires_grad = False
        self.lstm = nn.LSTM(feature_size, 128, 2, batch_first=True, dropout=dropout)
        self.head = nn.Sequential(nn.Dropout(dropout), nn.Linear(128, classes))
        self.register_buffer("image_mean", torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1))
        self.register_buffer("image_std", torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1))

    @torch.jit.export
    def encode(self, frames: torch.Tensor) -> torch.Tensor:
        normalized = (frames - self.image_mean) / self.image_std
        return self.encoder(normalized).flatten(1)

    @torch.jit.export
    def classify(self, features: torch.Tensor, lengths: torch.Tensor) -> torch.Tensor:
        sequence, _ = self.lstm(features)
        last = sequence[torch.arange(sequence.size(0), device=sequence.device), lengths - 1]
        return self.head(last)

    def forward(self, frames: torch.Tensor, lengths: torch.Tensor) -> torch.Tensor:
        batch, length = frames.size(0), frames.size(1)
        encoded = self.encode(frames.flatten(0, 1)).reshape(batch, length, -1)
        return self.classify(encoded, lengths)
