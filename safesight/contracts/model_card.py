"""Versioned immutable model, qualification, and deployment contracts."""

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Postprocessing(BaseModel):
    """Detector candidate and display floors, independent from alert calibration."""

    model_config = ConfigDict(extra="forbid")
    nms_iou: float = Field(default=0.45, gt=0, le=1)
    containment_threshold: float = Field(default=0.8, gt=0, le=1)
    inference_floor: float = Field(default=0.05, ge=0.01, le=1)
    display_floor: float = Field(default=0.10, ge=0.01, le=1)

    @model_validator(mode="after")
    def coherent(self):
        if self.display_floor < self.inference_floor:
            raise ValueError("display_floor must not be lower than inference_floor")
        return self


class ModelCard(BaseModel):
    """Immutable facts produced by training; schema v1 remains readable only for compatibility."""

    model_config = ConfigDict(extra="allow")
    schema_version: Literal[1, 2] = 1
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
    postprocessing: Postprocessing = Field(default_factory=Postprocessing)


class QualificationAttestation(BaseModel):
    """Immutable qualification evidence bound to one exact model card."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    slug: str
    run_id: str
    model_card_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    qualification_dataset_hash: str
    qualification_config_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    thresholds: dict[str, float]
    quality: dict[str, Any]
    metrics: dict[str, Any]
    created_at: str


class DeploymentPointer(BaseModel):
    """Small active pointer; production deployment always references a PASS attestation."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    slug: str
    run_id: str
    model_card: str
    model_card_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    qualification: str
    qualification_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    activated_at: str


def contract_sha256(value: BaseModel | dict) -> str:
    """Hash canonical contract content independently of JSON formatting."""
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
