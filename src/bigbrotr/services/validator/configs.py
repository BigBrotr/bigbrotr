"""Validator service configuration models.

See Also:
    [Validator][bigbrotr.services.validator.Validator]: The service class
        that consumes these configurations.
    [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
        Base class providing ``interval``, ``max_consecutive_failures``,
        and ``metrics`` fields.
"""

from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from bigbrotr.core.base_service import BaseServiceConfig
from bigbrotr.services.common.configs import NetworksConfig


def _require_bool(value: Any, field_name: str) -> bool:
    """Require canonical booleans for authored validator config boundaries."""
    if not isinstance(value, bool):
        raise ValueError(f"{field_name}: expected bool, got {type(value).__name__}")
    return value


def _require_int(value: Any, field_name: str) -> int:
    """Require canonical integers for authored validator config boundaries."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name}: expected integer, got {type(value).__name__}")
    return int(value)


def _require_number(value: Any, field_name: str) -> int | float:
    """Require canonical numeric types for authored validator config boundaries."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name}: expected number, got {type(value).__name__}")
    return cast("int | float", value)


class ProcessingConfig(BaseModel):
    """Candidate processing settings.

    Attributes:
        chunk_size: Candidates to fetch and validate per iteration. Larger
            chunks reduce DB round-trips but increase memory usage.
        max_candidates: Optional cap on total candidates per cycle
            (``None`` = all).
        interval: Minimum seconds before retrying a failed candidate.
            Candidates whose ``timestamp`` is within this window are
            skipped.

    See Also:
        [ValidatorConfig][bigbrotr.services.validator.ValidatorConfig]:
            Parent config that embeds this model.
    """

    model_config = ConfigDict(extra="forbid")

    chunk_size: int = Field(
        default=100, ge=10, le=1000, description="Candidates to fetch and validate per iteration"
    )
    max_candidates: int | None = Field(
        default=None, ge=1, description="Maximum candidates per cycle (None = all)"
    )
    interval: float = Field(
        default=3600.0,
        ge=0.0,
        le=604_800.0,
        description="Minimum seconds before retrying a failed candidate",
    )
    allow_insecure: bool = Field(
        default=False,
        description="Fall back to insecure transport on SSL certificate failure",
    )

    @model_validator(mode="before")
    @classmethod
    def require_string_field_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            invalid_key = next((key for key in data if not isinstance(key, str)), None)
            if invalid_key is not None:
                raise ValueError(f"config: expected string keys, got {type(invalid_key).__name__}")
        return data

    @field_validator("chunk_size", mode="before")
    @classmethod
    def require_integer_chunk_size(cls, v: Any, info: ValidationInfo) -> int:
        """Require canonical integers for per-cycle candidate batch sizing."""
        field_name = info.field_name or "chunk_size"
        return _require_int(v, field_name)

    @field_validator("max_candidates", mode="before")
    @classmethod
    def require_integer_max_candidates(cls, v: Any, info: ValidationInfo) -> Any:
        """Require canonical integers for the optional cycle-wide candidate cap."""
        if v is None:
            return v
        field_name = info.field_name or "max_candidates"
        return _require_int(v, field_name)

    @field_validator("interval", mode="before")
    @classmethod
    def require_numeric_interval(cls, v: Any, info: ValidationInfo) -> int | float:
        """Require canonical numeric types for the failed-candidate retry window."""
        field_name = info.field_name or "interval"
        return _require_number(v, field_name)

    @field_validator("allow_insecure", mode="before")
    @classmethod
    def require_boolean_allow_insecure(cls, v: Any, info: ValidationInfo) -> bool:
        """Require canonical booleans for the TLS fallback policy."""
        field_name = info.field_name or "allow_insecure"
        return _require_bool(v, field_name)


class CleanupConfig(BaseModel):
    """Exhausted candidate cleanup settings.

    Removes candidates that have exceeded the maximum failure threshold,
    preventing permanently broken relays from consuming resources.

    Attributes:
        enabled: Whether to enable exhausted candidate cleanup.
        max_failures: Failure threshold after which candidates are removed.

    See Also:
        [delete_exhausted_candidates][bigbrotr.services.validator.queries.delete_exhausted_candidates]:
            The SQL query driven by ``max_failures``.
        [ValidatorConfig][bigbrotr.services.validator.ValidatorConfig]:
            Parent config that embeds this model.
    """

    enabled: bool = Field(default=True, description="Enable exhausted candidate cleanup")
    max_failures: int = Field(
        default=720, ge=1, description="Failure threshold for candidate removal"
    )

    @model_validator(mode="before")
    @classmethod
    def require_string_field_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            invalid_key = next((key for key in data if not isinstance(key, str)), None)
            if invalid_key is not None:
                raise ValueError(f"config: expected string keys, got {type(invalid_key).__name__}")
        return data

    @field_validator("max_failures", mode="before")
    @classmethod
    def require_integer_max_failures(cls, v: Any, info: ValidationInfo) -> int:
        """Require canonical integers for the exhausted-candidate failure threshold."""
        field_name = info.field_name or "max_failures"
        return _require_int(v, field_name)

    @field_validator("enabled", mode="before")
    @classmethod
    def require_boolean_enabled(cls, v: Any, info: ValidationInfo) -> bool:
        """Require canonical booleans for cleanup enablement."""
        field_name = info.field_name or "enabled"
        return _require_bool(v, field_name)


class ValidatorConfig(BaseServiceConfig):
    """Validator service configuration.

    See Also:
        [Validator][bigbrotr.services.validator.Validator]: The service
            class that consumes this configuration.
        [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
            Base class providing ``interval``, ``max_consecutive_failures``,
            and ``metrics`` fields.
        [NetworksConfig][bigbrotr.services.common.configs.NetworksConfig]:
            Per-network timeout and proxy settings.
    """

    @model_validator(mode="before")
    @classmethod
    def require_string_field_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            invalid_key = next((key for key in data if not isinstance(key, str)), None)
            if invalid_key is not None:
                raise ValueError(f"config: expected string keys, got {type(invalid_key).__name__}")
        return data

    networks: NetworksConfig = Field(
        default_factory=NetworksConfig, description="Per-network connection settings"
    )
    processing: ProcessingConfig = Field(
        default_factory=ProcessingConfig, description="Candidate processing settings"
    )
    cleanup: CleanupConfig = Field(
        default_factory=CleanupConfig, description="Exhausted candidate cleanup settings"
    )
