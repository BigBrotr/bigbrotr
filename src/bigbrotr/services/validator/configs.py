"""Validator service configuration models.

See Also:
    [Validator][bigbrotr.services.validator.Validator]: The service class
        that consumes these configurations.
    [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
        Base class providing ``interval``, ``max_consecutive_failures``,
        and ``metrics`` fields.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from bigbrotr.core.base_service import BaseServiceConfig
from bigbrotr.services.common.configs import NetworkConfig


class ProcessingConfig(BaseModel):
    """Candidate processing settings.

    Attributes:
        chunk_size: Candidates to fetch and validate per iteration. Larger
            chunks reduce DB round-trips but increase memory usage.
        max_candidates: Optional cap on total candidates per cycle
            (``None`` = all).

    See Also:
        [ValidatorConfig][bigbrotr.services.validator.ValidatorConfig]:
            Parent config that embeds this model.
    """

    chunk_size: int = Field(default=100, ge=10, le=1000)
    max_candidates: int | None = Field(default=None, ge=1)


class CleanupConfig(BaseModel):
    """Exhausted candidate cleanup settings.

    Removes candidates that have exceeded the maximum failure threshold,
    preventing permanently broken relays from consuming resources.

    Attributes:
        enabled: Whether to enable exhausted candidate cleanup.
        max_failures: Failure threshold after which candidates are removed.

    See Also:
        [delete_exhausted_candidates][bigbrotr.services.common.queries.delete_exhausted_candidates]:
            The SQL query driven by ``max_failures``.
        [ValidatorConfig][bigbrotr.services.validator.ValidatorConfig]:
            Parent config that embeds this model.
    """

    enabled: bool = Field(default=False)
    max_failures: int = Field(default=100, ge=1)


class ValidatorConfig(BaseServiceConfig):
    """Validator service configuration.

    See Also:
        [Validator][bigbrotr.services.validator.Validator]: The service
            class that consumes this configuration.
        [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
            Base class providing ``interval``, ``max_consecutive_failures``,
            and ``metrics`` fields.
        [NetworkConfig][bigbrotr.services.common.configs.NetworkConfig]:
            Per-network timeout and proxy settings.
    """

    networks: NetworkConfig = Field(default_factory=NetworkConfig)
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    cleanup: CleanupConfig = Field(default_factory=CleanupConfig)
