"""API service configuration models.

See Also:
    [Api][bigbrotr.services.api.Api]: The service class that consumes
        these configurations.
    [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
        Base class providing ``interval``, ``max_consecutive_failures``,
        and ``metrics`` fields.
"""

from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, Field, field_validator, model_validator

from bigbrotr.core.base_service import BaseServiceConfig
from bigbrotr.services.common.configs import ReadModelConfig  # noqa: TC001 (Pydantic runtime)
from bigbrotr.services.common.read_models import read_models_for_surface


class ApiConfig(BaseServiceConfig):
    """Configuration for the API service.

    Attributes:
        host: Bind address for the HTTP server.
        port: Port for the HTTP server.
        route_prefix: URL prefix for all API routes (e.g. ``/v1``, ``/api/v1``).
        max_page_size: Hard ceiling on the ``limit`` query parameter.
        default_page_size: Default ``limit`` when not specified.
        read_models: Per-read-model access policies. The legacy YAML key
            ``tables`` is still accepted as an input alias. Read models
            not listed here default to disabled.
        cors_origins: Allowed CORS origins.  Empty list disables CORS.
        request_timeout: HTTP request timeout in seconds.
    """

    title: str = Field(
        default="BigBrotr API",
        min_length=1,
        description="FastAPI application title",
    )
    host: str = Field(
        default="0.0.0.0",  # noqa: S104
        min_length=1,
        description="HTTP bind address",
    )
    port: int = Field(
        default=8080,
        ge=1,
        le=65535,
        description="HTTP port",
    )
    route_prefix: str = Field(
        default="/v1",
        min_length=1,
        description="URL prefix for all API routes",
    )
    max_page_size: int = Field(
        default=1000,
        ge=1,
        le=10000,
        description="Hard ceiling on the limit query parameter",
    )
    default_page_size: int = Field(
        default=100,
        ge=1,
        le=10000,
        description="Default limit when not specified",
    )
    read_models: dict[str, ReadModelConfig] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("read_models", "tables"),
        description="Per-read-model access policies",
    )
    cors_origins: list[str] = Field(
        default_factory=list,
        description="Allowed CORS origins (empty = disabled)",
    )
    request_timeout: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        description="Per-request timeout in seconds",
    )

    @field_validator("route_prefix")
    @classmethod
    def _normalize_route_prefix(cls, v: str) -> str:
        v = v.strip("/")
        if not v:
            msg = "route_prefix must not be empty"
            raise ValueError(msg)
        return f"/{v}"

    @model_validator(mode="after")
    def _validate_page_sizes(self) -> ApiConfig:
        if self.default_page_size > self.max_page_size:
            msg = (
                f"default_page_size ({self.default_page_size}) "
                f"must not exceed max_page_size ({self.max_page_size})"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _validate_port_conflict(self) -> ApiConfig:
        if self.metrics.enabled and self.metrics.port == self.port:
            raise ValueError(
                f"metrics.port ({self.metrics.port}) must differ from HTTP port ({self.port})"
            )
        return self

    @model_validator(mode="before")
    @classmethod
    def _reject_duplicate_read_model_keys(cls, data: Any) -> Any:
        if isinstance(data, dict) and "tables" in data and "read_models" in data:
            raise ValueError("Specify only one of tables or read_models")
        return data

    @model_validator(mode="after")
    def _validate_public_tables(self) -> ApiConfig:
        allowed_tables = set(read_models_for_surface("api"))
        invalid_tables = sorted(set(self.read_models) - allowed_tables)
        if invalid_tables:
            invalid = ", ".join(invalid_tables)
            allowed = ", ".join(sorted(allowed_tables))
            raise ValueError(
                "read_models contains non-public API read models: "
                f"{invalid}. Allowed read models: {allowed}"
            )
        return self
