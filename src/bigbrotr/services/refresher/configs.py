"""Refresher service configuration models.

See Also:
    [Refresher][bigbrotr.services.refresher.Refresher]: The service class
        that consumes these configurations.
    [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
        Base class providing ``interval``, ``max_consecutive_failures``,
        and ``metrics`` fields.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

from bigbrotr.core.base_service import BaseServiceConfig


_VIEW_NAME_PATTERN = re.compile(r"^[a-z_][a-z0-9_]*$")

#: Default view refresh order respecting 3-level dependency chain:
#: Level 1 — relay_metadata_latest (base dependency)
#: Level 2 — independent views
#: Level 3 — views depending on relay_metadata_latest
DEFAULT_VIEWS: list[str] = [
    "relay_metadata_latest",
    "event_stats",
    "relay_stats",
    "kind_counts",
    "kind_counts_by_relay",
    "pubkey_counts",
    "pubkey_counts_by_relay",
    "network_stats",
    "event_daily_counts",
    "relay_software_counts",
    "supported_nip_counts",
]


class RefreshConfig(BaseModel):
    """Configuration for materialized view refresh.

    See Also:
        [RefresherConfig][bigbrotr.services.refresher.RefresherConfig]: Parent
            config that embeds this model.
    """

    views: list[str] = Field(
        default_factory=lambda: list(DEFAULT_VIEWS),
        description="Ordered list of materialized view names to refresh.",
    )

    @field_validator("views")
    @classmethod
    def views_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("views list must not be empty")
        invalid = [name for name in v if not _VIEW_NAME_PATTERN.match(name)]
        if invalid:
            raise ValueError(
                f"invalid view names (must match [a-z_][a-z0-9_]*): {', '.join(invalid)}"
            )
        return v


class RefresherConfig(BaseServiceConfig):
    """Refresher service configuration.

    See Also:
        [Refresher][bigbrotr.services.refresher.Refresher]: The service class
            that consumes this configuration.
        [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
            Base class providing ``interval`` and ``metrics`` fields.
    """

    interval: float = Field(
        default=3600.0,
        ge=60.0,
        description="Target seconds between refresh cycle starts (fixed-schedule)",
    )
    refresh: RefreshConfig = Field(default_factory=RefreshConfig)
