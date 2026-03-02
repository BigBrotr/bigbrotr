"""API service configuration models.

See Also:
    [Api][bigbrotr.services.api.Api]: The service class that consumes
        these configurations.
    [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
        Base class providing ``interval``, ``max_consecutive_failures``,
        and ``metrics`` fields.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from bigbrotr.core.base_service import BaseServiceConfig
from bigbrotr.services.common.configs import TableConfig  # noqa: TC001 (Pydantic runtime)


class ApiConfig(BaseServiceConfig):
    """Configuration for the API service.

    Attributes:
        host: Bind address for the HTTP server.
        port: Port for the HTTP server.
        max_page_size: Hard ceiling on the ``limit`` query parameter.
        default_page_size: Default ``limit`` when not specified.
        tables: Per-table access policies.  Tables not listed here
            default to disabled.
        cors_origins: Allowed CORS origins.  Empty list disables CORS.
        request_timeout: HTTP request timeout in seconds.
    """

    host: str = Field(default="0.0.0.0", min_length=1, description="HTTP bind address")  # noqa: S104
    port: int = Field(default=8080, ge=1, le=65535, description="HTTP port")
    max_page_size: int = Field(default=1000, ge=1, le=10000)
    default_page_size: int = Field(default=100, ge=1, le=10000)
    tables: dict[str, TableConfig] = Field(default_factory=dict)
    cors_origins: list[str] = Field(default_factory=list)
    request_timeout: float = Field(default=30.0, ge=1.0, le=300.0)

    @model_validator(mode="after")
    def _validate_page_sizes(self) -> ApiConfig:
        if self.default_page_size > self.max_page_size:
            msg = (
                f"default_page_size ({self.default_page_size}) "
                f"must not exceed max_page_size ({self.max_page_size})"
            )
            raise ValueError(msg)
        return self
