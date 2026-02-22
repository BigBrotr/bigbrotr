"""Finder service configuration models.

See Also:
    [Finder][bigbrotr.services.finder.Finder]: The service class
        that consumes these configurations.
    [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
        Base class providing ``interval`` and ``log_level`` fields.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from bigbrotr.core.base_service import BaseServiceConfig
from bigbrotr.models.constants import EventKind


class ConcurrencyConfig(BaseModel):
    """Concurrency limits for parallel API requests.

    See Also:
        [FinderConfig][bigbrotr.services.finder.FinderConfig]: Parent
            config that embeds this model.
    """

    max_parallel: int = Field(default=5, ge=1, le=20, description="Maximum concurrent API requests")


class EventsConfig(BaseModel):
    """Event scanning configuration for discovering relay URLs from stored events.

    Requires a full database schema with ``tags``, ``tagvalues``, and ``content``
    columns. Set ``enabled=false`` for minimal-schema implementations (e.g., LilBrotr).

    See Also:
        [get_events_with_relay_urls][bigbrotr.services.common.queries.get_events_with_relay_urls]:
            The SQL query driven by ``batch_size`` and ``kinds``.
        [FinderConfig][bigbrotr.services.finder.FinderConfig]: Parent
            config that embeds this model.
    """

    enabled: bool = Field(
        default=True,
        description="Enable event scanning (requires full schema with tags/content columns)",
    )
    batch_size: int = Field(
        default=1000, ge=100, le=10_000, description="Events to process per batch"
    )
    kinds: list[int] = Field(
        default_factory=lambda: [int(EventKind.CONTACTS), int(EventKind.RELAY_LIST)],
        description="Event kinds to scan (3=contacts, 10002=relay list)",
    )


class ApiSourceConfig(BaseModel):
    """Single API source configuration."""

    url: str = Field(description="API endpoint URL")
    enabled: bool = Field(default=True, description="Enable this source")
    timeout: float = Field(default=30.0, ge=0.1, le=120.0, description="Request timeout")
    connect_timeout: float = Field(
        default=10.0,
        ge=0.1,
        le=60.0,
        description="HTTP connection timeout (capped to total timeout)",
    )


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
            Base class providing ``interval`` and ``log_level`` fields.
    """

    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    events: EventsConfig = Field(default_factory=EventsConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
