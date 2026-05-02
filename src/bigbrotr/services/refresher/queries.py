"""Database query registry for the refresher service.

Each target maps to one SQL refresh function and one source watermark. The
service never builds target names dynamically from user input; it only executes
functions declared in this module-level registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from .configs import (
    DEFAULT_ANALYTICS_TARGETS,
    DEFAULT_CURRENT_TARGETS,
    AnalyticsRefreshTarget,
    CurrentRefreshTarget,
    IncrementalRefreshTarget,
    PeriodicRefreshTarget,
)


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr


class WatermarkSource(StrEnum):
    """Append-only source used to checkpoint one incremental target."""

    EVENT_OBSERVATION = "event_observation"
    RELAY_DOCUMENT = "relay_document"


@dataclass(frozen=True, slots=True)
class IncrementalRefreshTargetSpec:
    """SQL contract for one incremental refresh target."""

    target: IncrementalRefreshTarget
    target_group: str
    watermark_source: WatermarkSource
    sql_function: str
    metric_key: str


@dataclass(frozen=True, slots=True)
class PeriodicRefreshTargetSpec:
    """SQL contract for one periodic refresh target."""

    target: PeriodicRefreshTarget
    sql_function: str
    metric_key: str


_RELAY_DOCUMENT_TARGETS: frozenset[IncrementalRefreshTarget] = frozenset(
    {
        CurrentRefreshTarget.RELAY_DOCUMENT_CURRENT,
        AnalyticsRefreshTarget.RELAY_SOFTWARE_COUNTS,
        AnalyticsRefreshTarget.SUPPORTED_NIP_COUNTS,
    }
)

INCREMENTAL_REFRESH_TARGET_SPECS: dict[IncrementalRefreshTarget, IncrementalRefreshTargetSpec] = {
    **{
        target: IncrementalRefreshTargetSpec(
            target=target,
            target_group="current",
            watermark_source=(
                WatermarkSource.RELAY_DOCUMENT
                if target in _RELAY_DOCUMENT_TARGETS
                else WatermarkSource.EVENT_OBSERVATION
            ),
            sql_function=f"{target.value}_refresh",
            metric_key=target.value,
        )
        for target in DEFAULT_CURRENT_TARGETS
    },
    **{
        target: IncrementalRefreshTargetSpec(
            target=target,
            target_group="analytics",
            watermark_source=(
                WatermarkSource.RELAY_DOCUMENT
                if target in _RELAY_DOCUMENT_TARGETS
                else WatermarkSource.EVENT_OBSERVATION
            ),
            sql_function=f"{target.value}_refresh",
            metric_key=target.value,
        )
        for target in DEFAULT_ANALYTICS_TARGETS
    },
}

PERIODIC_REFRESH_TARGET_SPECS: dict[PeriodicRefreshTarget, PeriodicRefreshTargetSpec] = {
    PeriodicRefreshTarget.ROLLING_WINDOWS: PeriodicRefreshTargetSpec(
        target=PeriodicRefreshTarget.ROLLING_WINDOWS,
        sql_function="rolling_windows_refresh",
        metric_key=PeriodicRefreshTarget.ROLLING_WINDOWS.value,
    ),
    PeriodicRefreshTarget.RELAY_STATS_DOCUMENT: PeriodicRefreshTargetSpec(
        target=PeriodicRefreshTarget.RELAY_STATS_DOCUMENT,
        sql_function="relay_stats_document_refresh",
        metric_key=PeriodicRefreshTarget.RELAY_STATS_DOCUMENT.value,
    ),
    PeriodicRefreshTarget.NIP85_FOLLOWERS: PeriodicRefreshTargetSpec(
        target=PeriodicRefreshTarget.NIP85_FOLLOWERS,
        sql_function="nip85_follower_count_refresh",
        metric_key=PeriodicRefreshTarget.NIP85_FOLLOWERS.value,
    ),
}


def _require_refresh_non_negative_int(value: object, *, field_name: str) -> int:
    """Return one canonical non-negative integer from refresher query results."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an int")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return value


def _normalize_optional_refresh_non_negative_int(
    value: object,
    *,
    field_name: str,
) -> int | None:
    """Return one optional non-negative refresher integer result."""
    if value is None:
        return None
    return _require_refresh_non_negative_int(value, field_name=field_name)


def get_incremental_target_spec(
    target: IncrementalRefreshTarget,
) -> IncrementalRefreshTargetSpec:
    """Return the registry entry for one incremental target."""
    return INCREMENTAL_REFRESH_TARGET_SPECS[target]


def get_periodic_target_spec(target: PeriodicRefreshTarget) -> PeriodicRefreshTargetSpec:
    """Return the registry entry for one periodic target."""
    return PERIODIC_REFRESH_TARGET_SPECS[target]


async def get_event_observation_watermark(brotr: Brotr) -> int:
    """Return the latest visible ``event_observation.observed_at`` watermark."""
    result = await brotr.fetchval("SELECT COALESCE(MAX(observed_at), 0) FROM event_observation")
    if result is None:
        return 0
    return _require_refresh_non_negative_int(result, field_name="observed_at")


async def get_relay_document_watermark(brotr: Brotr) -> int:
    """Return the latest visible ``relay_document.associated_at`` watermark."""
    result = await brotr.fetchval("SELECT COALESCE(MAX(associated_at), 0) FROM relay_document")
    if result is None:
        return 0
    return _require_refresh_non_negative_int(result, field_name="associated_at")


def _bounded_source_until(
    *,
    after: int,
    min_pending: int | None,
    max_pending: int | None,
    max_source_window: int | None,
) -> int:
    """Return the bounded upper watermark for one incremental source slice."""
    normalized_min_pending = _normalize_optional_refresh_non_negative_int(
        min_pending,
        field_name="min_pending",
    )
    normalized_max_pending = _normalize_optional_refresh_non_negative_int(
        max_pending,
        field_name="max_pending",
    )
    if normalized_min_pending is None or normalized_max_pending is None:
        return after
    if normalized_min_pending > normalized_max_pending:
        raise ValueError("min_pending cannot exceed max_pending")
    if max_source_window is None:
        return normalized_max_pending
    return min(normalized_max_pending, normalized_min_pending + max_source_window)


async def get_max_observed_at(
    brotr: Brotr,
    after: int,
    max_source_window: int | None = None,
) -> int:
    """Return the bounded ``event_observation.observed_at`` upper watermark."""
    row = await brotr.fetchrow(
        """
        SELECT MIN(observed_at) AS min_observed_at, MAX(observed_at) AS max_observed_at
        FROM event_observation
        WHERE observed_at > $1
        """,
        after,
    )
    if row is None:
        return after
    return _bounded_source_until(
        after=after,
        min_pending=row["min_observed_at"],
        max_pending=row["max_observed_at"],
        max_source_window=max_source_window,
    )


async def get_max_associated_at(
    brotr: Brotr,
    after: int,
    max_source_window: int | None = None,
) -> int:
    """Return the bounded ``relay_document.associated_at`` upper watermark."""
    row = await brotr.fetchrow(
        """
        SELECT MIN(associated_at) AS min_associated_at, MAX(associated_at) AS max_associated_at
        FROM relay_document
        WHERE associated_at > $1
        """,
        after,
    )
    if row is None:
        return after
    return _bounded_source_until(
        after=after,
        min_pending=row["min_associated_at"],
        max_pending=row["max_associated_at"],
        max_source_window=max_source_window,
    )


async def refresh_incremental_target(
    brotr: Brotr,
    target: IncrementalRefreshTarget,
    after: int,
    until: int,
) -> int:
    """Execute the registered SQL refresh function for one incremental target."""
    spec = get_incremental_target_spec(target)
    result = await brotr.fetchval(
        f"SELECT {spec.sql_function}($1::BIGINT, $2::BIGINT)",
        after,
        until,
    )
    if result is None:
        return 0
    return _require_refresh_non_negative_int(result, field_name="refreshed_rows")


async def refresh_periodic_target(brotr: Brotr, target: PeriodicRefreshTarget) -> None:
    """Execute the registered SQL refresh function for one periodic target."""
    spec = get_periodic_target_spec(target)
    await brotr.execute(f"SELECT {spec.sql_function}()")
