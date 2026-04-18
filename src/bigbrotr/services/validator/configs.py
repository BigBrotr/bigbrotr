"""Validator service configuration models.

See Also:
    [Validator][bigbrotr.services.validator.Validator]: The service class
        that consumes these configurations.
    [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
        Base class providing ``interval``, ``max_consecutive_failures``,
        and ``metrics`` fields.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from bigbrotr.core.base_service import BaseServiceConfig
from bigbrotr.services.common.configs import NetworksConfig


def _reject_bool_alias(value: Any, field_name: str, expected: str) -> Any:
    """Reject boolean aliases for numeric validator config fields."""
    if isinstance(value, bool):
        raise ValueError(f"{field_name}: expected {expected}, got bool")
    return value


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

    @field_validator("max_candidates", mode="before")
    @classmethod
    def reject_boolean_max_candidates(cls, v: Any, info: ValidationInfo) -> Any:
        """Reject boolean aliases that would otherwise coerce to a one-item cycle budget."""
        if v is None:
            return v
        field_name = info.field_name or "max_candidates"
        return _reject_bool_alias(v, field_name, "integer")

    @field_validator("interval", mode="before")
    @classmethod
    def reject_boolean_interval(cls, v: Any, info: ValidationInfo) -> Any:
        """Reject boolean aliases that would otherwise coerce to retry windows."""
        field_name = info.field_name or "interval"
        return _reject_bool_alias(v, field_name, "number")


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

    @field_validator("max_failures", mode="before")
    @classmethod
    def reject_boolean_max_failures(cls, v: Any, info: ValidationInfo) -> Any:
        """Reject boolean aliases that would otherwise coerce to a failure threshold of 1/0."""
        field_name = info.field_name or "max_failures"
        return _reject_bool_alias(v, field_name, "integer")


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

    networks: NetworksConfig = Field(
        default_factory=NetworksConfig, description="Per-network connection settings"
    )
    processing: ProcessingConfig = Field(
        default_factory=ProcessingConfig, description="Candidate processing settings"
    )
    cleanup: CleanupConfig = Field(
        default_factory=CleanupConfig, description="Exhausted candidate cleanup settings"
    )
