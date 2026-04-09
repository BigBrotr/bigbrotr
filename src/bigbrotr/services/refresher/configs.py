"""Refresher service configuration models.

See Also:
    [Refresher][bigbrotr.services.refresher.Refresher]: The service class
        that consumes these configurations.
    [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
        Base class providing ``interval``, ``max_consecutive_failures``,
        and ``metrics`` fields.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bigbrotr.core.base_service import BaseServiceConfig


TargetT = TypeVar("TargetT", bound=StrEnum)


class CurrentRefreshTarget(StrEnum):
    """Current-state tables maintained by the refresher in dependency order."""

    RELAY_METADATA_CURRENT = "relay_metadata_current"
    EVENTS_REPLACEABLE_CURRENT = "events_replaceable_current"
    EVENTS_ADDRESSABLE_CURRENT = "events_addressable_current"
    CONTACT_LISTS_CURRENT = "contact_lists_current"
    CONTACT_LIST_EDGES_CURRENT = "contact_list_edges_current"


class AnalyticsRefreshTarget(StrEnum):
    """Analytics tables maintained by the refresher in dependency order."""

    DAILY_COUNTS = "daily_counts"
    RELAY_SOFTWARE_COUNTS = "relay_software_counts"
    SUPPORTED_NIP_COUNTS = "supported_nip_counts"
    PUBKEY_KIND_STATS = "pubkey_kind_stats"
    PUBKEY_RELAY_STATS = "pubkey_relay_stats"
    RELAY_KIND_STATS = "relay_kind_stats"
    PUBKEY_STATS = "pubkey_stats"
    KIND_STATS = "kind_stats"
    RELAY_STATS = "relay_stats"
    NIP85_PUBKEY_STATS = "nip85_pubkey_stats"
    NIP85_EVENT_STATS = "nip85_event_stats"
    NIP85_ADDRESSABLE_STATS = "nip85_addressable_stats"
    NIP85_IDENTIFIER_STATS = "nip85_identifier_stats"


class PeriodicRefreshTarget(StrEnum):
    """Periodic reconciliation tasks run after incremental table refreshes."""

    ROLLING_WINDOWS = "rolling_windows"
    RELAY_STATS_METADATA = "relay_stats_metadata"
    NIP85_FOLLOWERS = "nip85_followers"


IncrementalRefreshTarget = CurrentRefreshTarget | AnalyticsRefreshTarget

DEFAULT_CURRENT_TARGETS: tuple[CurrentRefreshTarget, ...] = tuple(CurrentRefreshTarget)
DEFAULT_ANALYTICS_TARGETS: tuple[AnalyticsRefreshTarget, ...] = tuple(AnalyticsRefreshTarget)
DEFAULT_PERIODIC_TARGETS: tuple[PeriodicRefreshTarget, ...] = tuple(PeriodicRefreshTarget)

_TARGET_DEPENDENCIES: dict[str, frozenset[str]] = {
    CurrentRefreshTarget.CONTACT_LISTS_CURRENT.value: frozenset(
        {CurrentRefreshTarget.EVENTS_REPLACEABLE_CURRENT.value}
    ),
    CurrentRefreshTarget.CONTACT_LIST_EDGES_CURRENT.value: frozenset(
        {CurrentRefreshTarget.CONTACT_LISTS_CURRENT.value}
    ),
    AnalyticsRefreshTarget.RELAY_SOFTWARE_COUNTS.value: frozenset(
        {CurrentRefreshTarget.RELAY_METADATA_CURRENT.value}
    ),
    AnalyticsRefreshTarget.SUPPORTED_NIP_COUNTS.value: frozenset(
        {CurrentRefreshTarget.RELAY_METADATA_CURRENT.value}
    ),
    AnalyticsRefreshTarget.PUBKEY_STATS.value: frozenset(
        {
            AnalyticsRefreshTarget.PUBKEY_KIND_STATS.value,
            AnalyticsRefreshTarget.PUBKEY_RELAY_STATS.value,
        }
    ),
    AnalyticsRefreshTarget.KIND_STATS.value: frozenset(
        {
            AnalyticsRefreshTarget.PUBKEY_KIND_STATS.value,
            AnalyticsRefreshTarget.RELAY_KIND_STATS.value,
        }
    ),
    AnalyticsRefreshTarget.RELAY_STATS.value: frozenset(
        {
            AnalyticsRefreshTarget.PUBKEY_RELAY_STATS.value,
            AnalyticsRefreshTarget.RELAY_KIND_STATS.value,
        }
    ),
}


def _normalize_targets(
    targets: list[TargetT],
    canonical: tuple[TargetT, ...],
    field_name: str,
) -> list[TargetT]:
    """Return selected targets in canonical order and reject duplicates."""
    seen: set[TargetT] = set()
    duplicates: list[str] = []
    for target in targets:
        if target in seen:
            duplicates.append(target.value)
        seen.add(target)

    if duplicates:
        raise ValueError(f"duplicate refresher targets in {field_name}: {', '.join(duplicates)}")

    selected = set(targets)
    return [target for target in canonical if target in selected]


def validate_refresh_dependencies(
    current_targets: list[CurrentRefreshTarget],
    analytics_targets: list[AnalyticsRefreshTarget],
) -> None:
    """Fail fast if the selected refresh set omits a required upstream dependency."""
    selected = {target.value for target in current_targets}
    selected.update(target.value for target in analytics_targets)

    problems: list[str] = []
    for target, required in _TARGET_DEPENDENCIES.items():
        if target not in selected:
            continue
        missing = sorted(required - selected)
        if missing:
            problems.append(f"{target} requires {', '.join(missing)}")
    if problems:
        raise ValueError("invalid refresher target selection: " + "; ".join(problems))


class ProcessingConfig(BaseModel):
    """Refresher cycle processing budgets and failure policy."""

    max_duration: float | None = Field(
        default=None,
        ge=1.0,
        le=86_400.0,
        description="Maximum seconds for one refresh cycle (None = unbounded)",
    )
    max_targets_per_cycle: int | None = Field(
        default=None,
        ge=1,
        description="Maximum targets to attempt in one cycle (None = all configured targets)",
    )
    continue_on_target_error: bool = Field(
        default=True,
        description="Continue refreshing later targets after one target fails",
    )


class CurrentRefreshConfig(BaseModel):
    """Current-state target selection."""

    model_config = ConfigDict(extra="forbid")

    targets: list[CurrentRefreshTarget] = Field(
        default_factory=lambda: list(DEFAULT_CURRENT_TARGETS),
        description="Current-state tables to refresh incrementally",
    )

    @field_validator("targets")
    @classmethod
    def normalize_targets(cls, targets: list[CurrentRefreshTarget]) -> list[CurrentRefreshTarget]:
        return _normalize_targets(targets, DEFAULT_CURRENT_TARGETS, "current.targets")


class AnalyticsRefreshConfig(BaseModel):
    """Analytics target selection."""

    model_config = ConfigDict(extra="forbid")

    targets: list[AnalyticsRefreshTarget] = Field(
        default_factory=lambda: list(DEFAULT_ANALYTICS_TARGETS),
        description="Analytics tables to refresh incrementally",
    )

    @field_validator("targets")
    @classmethod
    def normalize_targets(
        cls, targets: list[AnalyticsRefreshTarget]
    ) -> list[AnalyticsRefreshTarget]:
        return _normalize_targets(targets, DEFAULT_ANALYTICS_TARGETS, "analytics.targets")


class PeriodicRefreshConfig(BaseModel):
    """Periodic reconciliation task toggles."""

    model_config = ConfigDict(extra="forbid")

    rolling_windows: bool = Field(
        default=True,
        description="Recompute rolling time-window columns after incremental refreshes",
    )
    relay_stats_metadata: bool = Field(
        default=True,
        description="Refresh relay_stats metadata fields from current relay metadata",
    )
    nip85_followers: bool = Field(
        default=True,
        description="Recompute NIP-85 follower/following counts",
    )

    def enabled_targets(self) -> list[PeriodicRefreshTarget]:
        """Return enabled periodic tasks in canonical execution order."""
        return [target for target in DEFAULT_PERIODIC_TARGETS if getattr(self, target.value)]


class CleanupConfig(BaseModel):
    """Refresher checkpoint cleanup settings."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=True,
        description="Remove stale checkpoints for targets no longer configured",
    )


class RefresherConfig(BaseServiceConfig):
    """Refresher service configuration."""

    interval: float = Field(
        default=86400.0,
        ge=60.0,
        description="Target seconds between refresh cycle starts (fixed-schedule)",
    )
    processing: ProcessingConfig = Field(
        default_factory=ProcessingConfig,
        description="Cycle processing budgets and error policy",
    )
    current: CurrentRefreshConfig = Field(
        default_factory=CurrentRefreshConfig,
        description="Current-state refresh target configuration",
    )
    analytics: AnalyticsRefreshConfig = Field(
        default_factory=AnalyticsRefreshConfig,
        description="Analytics refresh target configuration",
    )
    periodic: PeriodicRefreshConfig = Field(
        default_factory=PeriodicRefreshConfig,
        description="Periodic reconciliation task configuration",
    )
    cleanup: CleanupConfig = Field(
        default_factory=CleanupConfig,
        description="Checkpoint cleanup configuration",
    )

    @model_validator(mode="after")
    def validate_target_dependencies(self) -> RefresherConfig:
        """Ensure configured targets include required upstream dependencies."""
        validate_refresh_dependencies(self.current.targets, self.analytics.targets)
        return self
