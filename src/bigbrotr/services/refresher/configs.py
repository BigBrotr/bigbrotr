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
#: Order: cross-tabs first, then entity tables that derive unique_* counts
#: from them, then canonical contact-list facts, then NIP-85 summary tables.
DEFAULT_SUMMARIES: list[str] = [
    "pubkey_kind_stats",
    "pubkey_relay_stats",
    "relay_kind_stats",
    "pubkey_stats",
    "kind_stats",
    "relay_stats",
    "contact_lists_current",
    "contact_list_edges_current",
    "nip85_pubkey_stats",
    "nip85_event_stats",
]

_CANONICAL_MATVIEWS: tuple[str, ...] = tuple(DEFAULT_MATVIEWS)
_CANONICAL_SUMMARIES: tuple[str, ...] = tuple(DEFAULT_SUMMARIES)
_SUMMARY_DEPENDENCIES: dict[str, frozenset[str]] = {
    "pubkey_stats": frozenset({"pubkey_kind_stats", "pubkey_relay_stats"}),
    "kind_stats": frozenset({"pubkey_kind_stats", "relay_kind_stats"}),
    "relay_stats": frozenset({"pubkey_relay_stats", "relay_kind_stats"}),
    "contact_list_edges_current": frozenset({"contact_lists_current"}),
}


def _validate_names(v: list[str], label: str) -> list[str]:
    if not v:
        raise ValueError(f"{label} list must not be empty")
    invalid = [name for name in v if not _VIEW_NAME_PATTERN.match(name)]
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


def resolve_matview_order(matviews: list[str]) -> list[str]:
    """Return matviews in canonical dependency order."""
    return _resolve_canonical_order(matviews, _CANONICAL_MATVIEWS)


def resolve_summary_order(summaries: list[str]) -> list[str]:
    """Return summary tables in canonical dependency order."""
    return _resolve_canonical_order(summaries, _CANONICAL_SUMMARIES)


def validate_summary_dependencies(summaries: list[str]) -> None:
    """Fail fast if a selected summary omits a required upstream dependency."""
    selected = set(summaries)
    problems: list[str] = []
    for summary, required in _SUMMARY_DEPENDENCIES.items():
        if summary not in selected:
            continue
        missing = sorted(required - selected)
        if missing:
            problems.append(f"{summary} requires {', '.join(missing)}")
    if problems:
        raise ValueError("invalid refresher summary selection: " + "; ".join(problems))


class RefreshConfig(BaseModel):
    """Configuration for materialized view and summary table refresh.

    Summary tables assume append-only ingestion of ``event_relay``; there is
    no full-rebuild path. Incremental refresh processes only new rows since the
    last checkpoint.

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
