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


_TABLE_NAME_PATTERN = re.compile(r"^[a-z_][a-z0-9_]*$")

#: Default incremental current-state tables maintained by the refresher.
#: Order is canonical and dependency-safe.
DEFAULT_CURRENT_TABLES: list[str] = [
    "relay_metadata_current",
    "events_replaceable_current",
    "events_addressable_current",
    "contact_lists_current",
    "contact_list_edges_current",
]

#: Default incremental analytics tables maintained by the refresher.
#: Order is canonical and dependency-safe.
DEFAULT_ANALYTICS_TABLES: list[str] = [
    "daily_counts",
    "relay_software_counts",
    "supported_nip_counts",
    "pubkey_kind_stats",
    "pubkey_relay_stats",
    "relay_kind_stats",
    "pubkey_stats",
    "kind_stats",
    "relay_stats",
    "nip85_pubkey_stats",
    "nip85_event_stats",
]

_CANONICAL_CURRENT_TABLES: tuple[str, ...] = tuple(DEFAULT_CURRENT_TABLES)
_CANONICAL_ANALYTICS_TABLES: tuple[str, ...] = tuple(DEFAULT_ANALYTICS_TABLES)
_TABLE_DEPENDENCIES: dict[str, frozenset[str]] = {
    "contact_lists_current": frozenset({"events_replaceable_current"}),
    "contact_list_edges_current": frozenset({"contact_lists_current"}),
    "relay_software_counts": frozenset({"relay_metadata_current"}),
    "supported_nip_counts": frozenset({"relay_metadata_current"}),
    "pubkey_stats": frozenset({"pubkey_kind_stats", "pubkey_relay_stats"}),
    "kind_stats": frozenset({"pubkey_kind_stats", "relay_kind_stats"}),
    "relay_stats": frozenset({"pubkey_relay_stats", "relay_kind_stats"}),
}


def _validate_names(v: list[str], label: str) -> list[str]:
    invalid = [name for name in v if not _TABLE_NAME_PATTERN.match(name)]
    if invalid:
        raise ValueError(
            f"invalid {label} names (must match [a-z_][a-z0-9_]*): {', '.join(invalid)}"
        )
    return v


def _resolve_canonical_order(names: list[str], canonical: tuple[str, ...]) -> list[str]:
    """Sort known names into canonical order while preserving unknown extras."""
    selected = set(names)
    ordered_known = [name for name in canonical if name in selected]
    ordered_extra = [name for name in names if name not in canonical]
    return [*ordered_known, *ordered_extra]


def resolve_current_table_order(current_tables: list[str]) -> list[str]:
    """Return current tables in canonical dependency order."""
    return _resolve_canonical_order(current_tables, _CANONICAL_CURRENT_TABLES)


def resolve_analytics_table_order(analytics_tables: list[str]) -> list[str]:
    """Return analytics tables in canonical dependency order."""
    return _resolve_canonical_order(analytics_tables, _CANONICAL_ANALYTICS_TABLES)


def validate_refresh_dependencies(current_tables: list[str], analytics_tables: list[str]) -> None:
    """Fail fast if the selected refresh set omits a required upstream dependency."""
    selected = set(current_tables) | set(analytics_tables)
    problems: list[str] = []
    for table, required in _TABLE_DEPENDENCIES.items():
        if table not in selected:
            continue
        missing = sorted(required - selected)
        if missing:
            problems.append(f"{table} requires {', '.join(missing)}")
    if problems:
        raise ValueError("invalid refresher table selection: " + "; ".join(problems))


class RefreshConfig(BaseModel):
    """Configuration for current-state and analytics table refresh.

    Each selected table is refreshed incrementally from its append-only source
    stream. The refresher stores checkpoints in ``service_state`` and resumes
    from the last successful watermark after restart.
    """

    current_tables: list[str] = Field(
        default_factory=lambda: list(DEFAULT_CURRENT_TABLES),
        description="Ordered list of current-state table names to refresh incrementally.",
    )

    analytics_tables: list[str] = Field(
        default_factory=lambda: list(DEFAULT_ANALYTICS_TABLES),
        description="Ordered list of analytics table names to refresh incrementally.",
    )

    @field_validator("current_tables")
    @classmethod
    def current_tables_valid(cls, v: list[str]) -> list[str]:
        return _validate_names(v, "current_tables")

    @field_validator("analytics_tables")
    @classmethod
    def analytics_tables_valid(cls, v: list[str]) -> list[str]:
        return _validate_names(v, "analytics_tables")


class RefresherConfig(BaseServiceConfig):
    """Refresher service configuration."""

    interval: float = Field(
        default=86400.0,
        ge=60.0,
        description="Target seconds between refresh cycle starts (fixed-schedule)",
    )
    refresh: RefreshConfig = Field(
        default_factory=RefreshConfig,
        description="Current-state and analytics table refresh settings",
    )
