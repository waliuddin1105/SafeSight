"""Lightweight persisted model metadata shared by API, training, and inference."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ModelCard(BaseModel):
    """Versioned contract for an independently replaceable model artifact."""

    model_config = ConfigDict(extra="allow")
    schema_version: int = 1
    slug: str
    loader: str
    architecture: str
    classes: list[str]
    artifact: str
    sha256: str
    run_id: str
    input_size: int
    thresholds: dict[str, float]
    quality: dict[str, Any]
    synthetic: bool = False
    sequence_length: int = 100
    sequence_fps: float = 5
    preprocessing: str = "v1"
    metrics: dict[str, Any] = Field(default_factory=dict)
