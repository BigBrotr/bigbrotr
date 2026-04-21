"""Configuration models for the Brotr database facade."""

from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_MIN_TIMEOUT_SECONDS = 0.1


def _reject_bool_alias(value: Any, field_name: str, expected: str) -> Any:
    """Reject boolean values for numeric config fields before pydantic coercion."""
    if isinstance(value, bool):
        raise ValueError(f"{field_name}: expected {expected}, got bool")
    return value


def _require_int(value: Any, field_name: str) -> int:
    """Require canonical integers for authored Brotr config boundaries."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name}: expected integer, got {type(value).__name__}")
    return int(value)


def _require_number(value: Any, field_name: str) -> int | float:
    """Require canonical numeric types for authored Brotr config boundaries."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name}: expected number, got {type(value).__name__}")
    return cast("int | float", value)


class BatchConfig(BaseModel):
    """Controls the maximum number of records per bulk insert operation."""

    model_config = ConfigDict(extra="forbid")

    max_size: int = Field(
        default=1000, ge=1, le=100_000, description="Maximum items per batch operation"
    )

    @model_validator(mode="before")
    @classmethod
    def require_string_field_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            invalid_key = next((key for key in data if not isinstance(key, str)), None)
            if invalid_key is not None:
                raise ValueError(f"config: expected string keys, got {type(invalid_key).__name__}")
        return data

    @field_validator("max_size", mode="before")
    @classmethod
    def require_integer_max_size(cls, value: Any) -> int:
        return _require_int(value, "max_size")


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

    @model_validator(mode="before")
    @classmethod
    def require_string_field_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            invalid_key = next((key for key in data if not isinstance(key, str)), None)
            if invalid_key is not None:
                raise ValueError(f"config: expected string keys, got {type(invalid_key).__name__}")
        return data

    @field_validator("query", "batch", "cleanup", "refresh", mode="before")
    @classmethod
    def require_numeric_timeouts(cls, value: Any, info: Any) -> Any:
        if value is None:
            return value
        field_name = getattr(info, "field_name", None) or "timeout"
        return _require_number(value, field_name)

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

    @model_validator(mode="before")
    @classmethod
    def require_string_field_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            invalid_key = next((key for key in data if not isinstance(key, str)), None)
            if invalid_key is not None:
                raise ValueError(f"config: expected string keys, got {type(invalid_key).__name__}")
        return data

    batch: BatchConfig = Field(default_factory=BatchConfig, description="Bulk insert size limits")
    timeouts: TimeoutsConfig = Field(
        default_factory=TimeoutsConfig, description="Per-category timeout settings"
    )
