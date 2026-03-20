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

#: Default materialized views (bounded output, full REFRESH CONCURRENTLY).
#: Order: relay_metadata_latest first (base dependency for software/NIP views),
#: then independent views, then views depending on relay_metadata_latest.
DEFAULT_MATVIEWS: list[str] = [
    "relay_metadata_latest",
    "daily_counts",
    "events_replaceable_latest",
    "events_addressable_latest",
    "relay_software_counts",
    "supported_nip_counts",
]

#: Default summary tables (incremental refresh via stored procedures).
#: Order: cross-tabs first (entity tables derive unique_* from them),
#: then NIP-85 tables (same incremental pattern).
DEFAULT_SUMMARIES: list[str] = [
    "pubkey_kind_stats",
    "pubkey_relay_stats",
    "relay_kind_stats",
    "pubkey_stats",
    "kind_stats",
    "relay_stats",
    "nip85_pubkey_stats",
    "nip85_event_stats",
]


def _validate_names(v: list[str], label: str) -> list[str]:
    if not v:
        raise ValueError(f"{label} list must not be empty")
    invalid = [name for name in v if not _VIEW_NAME_PATTERN.match(name)]
    if invalid:
        raise ValueError(
            f"invalid {label} names (must match [a-z_][a-z0-9_]*): {', '.join(invalid)}"
        )
    return v


class RefreshConfig(BaseModel):
    """Configuration for materialized view and summary table refresh.

    See Also:
        [RefresherConfig][bigbrotr.services.refresher.RefresherConfig]: Parent
            config that embeds this model.
    """

    matviews: list[str] = Field(
        default_factory=lambda: list(DEFAULT_MATVIEWS),
        description="Ordered list of matview names to refresh (full REFRESH CONCURRENTLY).",
    )

    summaries: list[str] = Field(
        default_factory=lambda: list(DEFAULT_SUMMARIES),
        description="Ordered list of summary table names to refresh incrementally.",
    )

    chunk_size: int = Field(
        default=2592000,
        ge=86400,
        description="Chunk size in seconds for full rebuild of summary tables.",
    )

    @field_validator("matviews")
    @classmethod
    def matviews_valid(cls, v: list[str]) -> list[str]:
        return _validate_names(v, "matviews")

    @field_validator("summaries")
    @classmethod
    def summaries_valid(cls, v: list[str]) -> list[str]:
        return _validate_names(v, "summaries")


class RefresherConfig(BaseServiceConfig):
    """Refresher service configuration.

    See Also:
        [Refresher][bigbrotr.services.refresher.Refresher]: The service class
            that consumes this configuration.
        [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
            Base class providing ``interval``, ``max_consecutive_failures``, and ``metrics`` fields.
    """

    interval: float = Field(
        default=86400.0,
        ge=60.0,
        description="Target seconds between refresh cycle starts (fixed-schedule)",
    )
    refresh: RefreshConfig = Field(
        default_factory=RefreshConfig, description="Materialized view and summary table settings"
    )
