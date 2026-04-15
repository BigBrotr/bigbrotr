"""Configuration models for the Brotr database facade."""

from pydantic import BaseModel, Field, field_validator


_MIN_TIMEOUT_SECONDS = 0.1


class BatchConfig(BaseModel):
    """Controls the maximum number of records per bulk insert operation."""

    max_size: int = Field(
        default=1000, ge=1, le=100_000, description="Maximum items per batch operation"
    )


class TimeoutsConfig(BaseModel):
    """Timeout settings for Brotr operations (in seconds)."""

    query: float | None = Field(
        default=60.0, le=3600.0, description="Query timeout (seconds, None=infinite)"
    )
    batch: float | None = Field(
        default=120.0, le=3600.0, description="Batch insert timeout (seconds, None=infinite)"
    )
    cleanup: float | None = Field(
        default=90.0, le=3600.0, description="Cleanup procedure timeout (seconds, None=infinite)"
    )
    refresh: float | None = Field(
        default=None,
        description="Long-running refresh procedure timeout (seconds, None=infinite)",
    )

    @field_validator("query", "batch", "cleanup", "refresh", mode="after")
    @classmethod
    def validate_timeout(cls, v: float | None) -> float | None:
        """Validate timeout: None (infinite) or >= 0.1 seconds."""
        if v is not None and v < _MIN_TIMEOUT_SECONDS:
            raise ValueError(
                f"Timeout must be None (infinite) or >= {_MIN_TIMEOUT_SECONDS} seconds"
            )
        return v


class BrotrConfig(BaseModel):
    """Aggregate configuration for the Brotr database facade."""

    batch: BatchConfig = Field(default_factory=BatchConfig, description="Bulk insert size limits")
    timeouts: TimeoutsConfig = Field(
        default_factory=TimeoutsConfig, description="Per-category timeout settings"
    )
