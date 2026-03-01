"""Finder service configuration models.

See Also:
    [Finder][bigbrotr.services.finder.Finder]: The service class
        that consumes these configurations.
    [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
        Base class providing ``interval`` and ``log_level`` fields.
"""

from __future__ import annotations

import jmespath
from pydantic import BaseModel, Field, field_validator, model_validator

from bigbrotr.core.base_service import BaseServiceConfig


class ConcurrencyConfig(BaseModel):
    """Concurrency limits for parallel operations.

    See Also:
        [FinderConfig][bigbrotr.services.finder.FinderConfig]: Parent
            config that embeds this model.
    """

    max_parallel_events: int = Field(
        default=10, ge=1, le=50, description="Maximum concurrent relay event scans"
    )


class EventsConfig(BaseModel):
    """Event scanning configuration for discovering relay URLs from stored events.

    Scans all events per relay (cursor-paginated by ``seen_at``) and extracts
    relay URLs from ``tagvalues``. Any tagvalue that parses as a valid relay
    URL becomes a validation candidate.

    See Also:
        [scan_event_relay][bigbrotr.services.common.queries.scan_event_relay]:
            The SQL query driven by ``batch_size``.
        [FinderConfig][bigbrotr.services.finder.FinderConfig]: Parent
            config that embeds this model.
    """

    enabled: bool = Field(default=True, description="Enable event scanning")
    batch_size: int = Field(
        default=1000, ge=100, le=10_000, description="Events to process per batch"
    )


class ApiSourceConfig(BaseModel):
    """Single API source configuration.

    The ``jmespath`` field declares how relay URL strings are extracted from
    the JSON response.  It accepts any valid
    `JMESPath <https://jmespath.org/>`_ expression.  The default ``[*]``
    assumes the response is a flat JSON array of URL strings.

    Examples of common expressions::

        [*]                   -- flat list of strings (default)
        data.relays           -- nested path to a list
        data.relays[*].url    -- list of objects, extract "url" field
        keys(@)               -- dict keys are the URLs

    See Also:
        [extract_urls_from_response][bigbrotr.services.finder.utils.extract_urls_from_response]:
            The extraction function driven by this field.
    """

    url: str = Field(description="API endpoint URL")
    enabled: bool = Field(default=True, description="Enable this source")
    timeout: float = Field(default=30.0, ge=0.1, le=120.0, description="Request timeout")
    connect_timeout: float = Field(
        default=10.0,
        ge=0.1,
        le=60.0,
        description="HTTP connection timeout (capped to total timeout)",
    )
    jmespath: str = Field(
        default="[*]",
        description="JMESPath expression to extract URL strings from the JSON response",
    )

    @model_validator(mode="after")
    def _validate_connect_timeout(self) -> ApiSourceConfig:
        if self.connect_timeout > self.timeout:
            raise ValueError(
                f"connect_timeout ({self.connect_timeout}) must not exceed timeout ({self.timeout})"
            )
        return self

    @field_validator("jmespath")
    @classmethod
    def _validate_jmespath(cls, v: str) -> str:
        try:
            jmespath.compile(v)
        except jmespath.exceptions.ParseError as e:
            msg = f"invalid JMESPath expression: {e}"
            raise ValueError(msg) from e
        return v


class ApiConfig(BaseModel):
    """API fetching configuration -- discovers relay URLs from public APIs.

    See Also:
        [ApiSourceConfig][bigbrotr.services.finder.ApiSourceConfig]:
            Per-source URL, timeout, and enablement settings.
        [FinderConfig][bigbrotr.services.finder.FinderConfig]: Parent
            config that embeds this model.
    """

    enabled: bool = Field(default=True, description="Enable API fetching")
    sources: list[ApiSourceConfig] = Field(
        default_factory=lambda: [
            ApiSourceConfig(url="https://api.nostr.watch/v1/online"),
            ApiSourceConfig(url="https://api.nostr.watch/v1/offline"),
        ]
    )
    delay_between_requests: float = Field(
        default=1.0, ge=0.0, le=10.0, description="Delay between API requests"
    )
    verify_ssl: bool = Field(
        default=True,
        description="Verify TLS certificates (disable only for testing/internal APIs)",
    )
    max_response_size: int = Field(
        default=5_242_880,
        ge=1024,
        le=52_428_800,
        description="Maximum API response body size in bytes (default: 5 MB)",
    )


class FinderConfig(BaseServiceConfig):
    """Finder service configuration.

    See Also:
        [Finder][bigbrotr.services.finder.Finder]: The service class
            that consumes this configuration.
        [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
            Base class providing ``interval`` and ``metrics`` fields.
    """

    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    events: EventsConfig = Field(default_factory=EventsConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
