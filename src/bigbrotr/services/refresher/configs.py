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
from typing import Any, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from bigbrotr.core.base_service import BaseServiceConfig


TargetT = TypeVar("TargetT", bound=StrEnum)


class CurrentRefreshTarget(StrEnum):
    """Narrow winner-map current tables maintained by the refresher."""

    RELAY_DOCUMENT_CURRENT = "relay_document_current"
    REPLACEABLE_EVENT_CURRENT = "replaceable_event_current"
    ADDRESSABLE_EVENT_CURRENT = "addressable_event_current"


class AnalyticsRefreshTarget(StrEnum):
    """Shared analytics and operational-fact tables maintained incrementally."""

    DAILY_COUNTS = "daily_counts"
    RELAY_SOFTWARE_COUNTS = "relay_software_counts"
    SUPPORTED_NIP_COUNTS = "supported_nip_counts"
    PUBKEY_KIND_STATS = "pubkey_kind_stats"
    PUBKEY_RELAY_STATS = "pubkey_relay_stats"
    RELAY_KIND_STATS = "relay_kind_stats"
    PUBKEY_STATS = "pubkey_stats"
    KIND_STATS = "kind_stats"
    RELAY_STATS = "relay_stats"
    CONTACT_LISTS_CURRENT = "contact_lists_current"
    CONTACT_LIST_EDGES_CURRENT = "contact_list_edges_current"
    NIP85_PUBKEY_STATS = "nip85_pubkey_stats"
    NIP85_EVENT_STATS = "nip85_event_stats"
    NIP85_ADDRESSABLE_STATS = "nip85_addressable_stats"
    NIP85_IDENTIFIER_STATS = "nip85_identifier_stats"


class PeriodicRefreshTarget(StrEnum):
    """Periodic reconciliation tasks run after incremental table refreshes."""

    ROLLING_WINDOWS = "rolling_windows"
    RELAY_STATS_DOCUMENT = "relay_stats_document"
    NIP85_FOLLOWERS = "nip85_followers"


IncrementalRefreshTarget = CurrentRefreshTarget | AnalyticsRefreshTarget

DEFAULT_CURRENT_TARGETS: tuple[CurrentRefreshTarget, ...] = tuple(CurrentRefreshTarget)
DEFAULT_ANALYTICS_TARGETS: tuple[AnalyticsRefreshTarget, ...] = tuple(AnalyticsRefreshTarget)
DEFAULT_PERIODIC_TARGETS: tuple[PeriodicRefreshTarget, ...] = tuple(PeriodicRefreshTarget)

_TARGET_DEPENDENCIES: dict[str, frozenset[str]] = {
    AnalyticsRefreshTarget.CONTACT_LISTS_CURRENT.value: frozenset(
        {CurrentRefreshTarget.REPLACEABLE_EVENT_CURRENT.value}
    ),
    AnalyticsRefreshTarget.CONTACT_LIST_EDGES_CURRENT.value: frozenset(
        {AnalyticsRefreshTarget.CONTACT_LISTS_CURRENT.value}
    ),
    AnalyticsRefreshTarget.RELAY_SOFTWARE_COUNTS.value: frozenset(
        {CurrentRefreshTarget.RELAY_DOCUMENT_CURRENT.value}
    ),
    AnalyticsRefreshTarget.SUPPORTED_NIP_COUNTS.value: frozenset(
        {CurrentRefreshTarget.RELAY_DOCUMENT_CURRENT.value}
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


def _reject_bool_alias(value: Any, field_name: str, expected_type: str) -> Any:
    """Reject bool aliases before Pydantic coerces them into numeric budgets."""
    if isinstance(value, bool):
        raise ValueError(f"{field_name}: expected {expected_type}, got bool")
    return value


def _require_bool(value: Any, field_name: str) -> bool:
    """Require canonical booleans for authored refresher config boundaries."""
    if not isinstance(value, bool):
        raise ValueError(f"{field_name}: expected bool, got {type(value).__name__}")
    return value


def _require_int(value: Any, field_name: str) -> int:
    """Require canonical integers for authored refresher config boundaries."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name}: expected integer, got {type(value).__name__}")
    return int(value)


def _require_number(value: Any, field_name: str) -> int | float:
    """Require canonical numeric types for authored refresher config boundaries."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name}: expected number, got {type(value).__name__}")
    return cast("int | float", value)


class ProcessingConfig(BaseModel):
    """Refresher cycle processing budgets and failure policy."""

    @model_validator(mode="before")
    @classmethod
    def require_string_field_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            invalid_key = next((key for key in data if not isinstance(key, str)), None)
            if invalid_key is not None:
                raise ValueError(f"config: expected string keys, got {type(invalid_key).__name__}")
        return data

    max_source_window: int | None = Field(
        default=86_400,
        ge=1,
        description=(
            "Maximum timestamp window per incremental source slice in seconds "
            "(None = consume through latest visible source watermark)"
        ),
    )
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

    @field_validator("max_source_window", "max_targets_per_cycle", mode="before")
    @classmethod
    def require_integer_budgets(cls, value: Any, info: ValidationInfo) -> Any:
        if value is None:
            return value
        return _require_int(value, str(info.field_name))

    @field_validator("max_duration", mode="before")
    @classmethod
    def require_numeric_duration_budget(cls, value: Any, info: ValidationInfo) -> Any:
        if value is None:
            return value
        return _require_number(value, str(info.field_name))

    @field_validator("continue_on_target_error", mode="before")
    @classmethod
    def require_boolean_continue_on_target_error(cls, value: Any, info: ValidationInfo) -> bool:
        return _require_bool(value, str(info.field_name))


class CurrentRefreshConfig(BaseModel):
    """Narrow winner-map current target selection."""

    model_config = ConfigDict(extra="forbid")

    targets: list[CurrentRefreshTarget] = Field(
        default_factory=lambda: list(DEFAULT_CURRENT_TARGETS),
        description="Narrow current winner-map tables to refresh incrementally",
    )

    @field_validator("targets")
    @classmethod
    def normalize_targets(cls, targets: list[CurrentRefreshTarget]) -> list[CurrentRefreshTarget]:
        return _normalize_targets(targets, DEFAULT_CURRENT_TARGETS, "current.targets")


class AnalyticsRefreshConfig(BaseModel):
    """Shared analytics and operational-fact target selection."""

    model_config = ConfigDict(extra="forbid")

    targets: list[AnalyticsRefreshTarget] = Field(
        default_factory=lambda: list(DEFAULT_ANALYTICS_TARGETS),
        description="Shared analytics and operational-fact tables to refresh incrementally",
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
    relay_stats_document: bool = Field(
        default=True,
        description="Refresh relay_stats document-backed fields from current relay documents",
    )
    nip85_followers: bool = Field(
        default=True,
        description="Recompute NIP-85 follower/following counts",
    )

    @field_validator("rolling_windows", "relay_stats_document", "nip85_followers", mode="before")
    @classmethod
    def require_boolean_toggles(cls, value: Any, info: ValidationInfo) -> bool:
        return _require_bool(value, str(info.field_name))

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

    @field_validator("enabled", mode="before")
    @classmethod
    def require_boolean_enabled(cls, value: Any, info: ValidationInfo) -> bool:
        return _require_bool(value, str(info.field_name))


class RefresherConfig(BaseServiceConfig):
    """Refresher service configuration."""

    @model_validator(mode="before")
    @classmethod
    def require_string_field_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            invalid_key = next((key for key in data if not isinstance(key, str)), None)
            if invalid_key is not None:
                raise ValueError(f"config: expected string keys, got {type(invalid_key).__name__}")
        return data

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

    @field_validator("interval", mode="before")
    @classmethod
    def require_numeric_interval(cls, value: Any, info: ValidationInfo) -> int | float:
        return _require_number(value, str(info.field_name))

    @model_validator(mode="after")
    def validate_target_dependencies(self) -> RefresherConfig:
        """Ensure configured targets include required upstream dependencies."""
        validate_refresh_dependencies(self.current.targets, self.analytics.targets)
        return self
