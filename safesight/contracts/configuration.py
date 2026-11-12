"""Validated runtime sampling and temporal configuration shared by API and worker."""

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TemporalRule(BaseModel):
    model_config = ConfigDict(extra="allow")
    n: int = Field(ge=1, strict=True)
    m: int = Field(ge=1, le=1000, strict=True)
    durations: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def coherent(self):
        import math

        if self.n > self.m or any(not math.isfinite(v) or v < 0 for v in self.durations.values()):
            raise ValueError("Temporal n must not exceed m; durations must be finite and nonnegative")
        return self


def validate_policy(policy: dict) -> dict:
    """Reject nonsensical policy values before decoding or model execution."""
    import math
    from safesight.contracts import SLUGS

    for slug in SLUGS:
        TemporalRule.model_validate(policy[slug])
    for name in ("sample_fps", "max_gap_seconds", "tracking_ttl_seconds"):
        value = policy[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")
    return policy
