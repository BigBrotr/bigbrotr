"""Runtime helpers for assertor publish cycles."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from bigbrotr.models.constants import EventKind


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from bigbrotr.core.base_service import BaseService
    from bigbrotr.services.assertor.configs import AssertorConfig


@dataclass(frozen=True, slots=True)
class PublishKindResult:
    """Outcome of publishing one assertor subject kind."""

    eligible: int = 0
    published: int = 0
    skipped: int = 0
    failed: int = 0
    duration_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class PublishCycleResult:
    """Outcome of one assertor publish cycle."""

    user: PublishKindResult = field(default_factory=PublishKindResult)
    event: PublishKindResult = field(default_factory=PublishKindResult)
    addressable: PublishKindResult = field(default_factory=PublishKindResult)
    identifier: PublishKindResult = field(default_factory=PublishKindResult)
    provider_profile: PublishKindResult = field(default_factory=PublishKindResult)
    checkpoint_cleanup_removed: int = 0

    @property
    def assertions_published(self) -> int:
        """Total assertion events published across NIP-85 subject kinds."""
        return (
            self.user.published
            + self.event.published
            + self.addressable.published
            + self.identifier.published
        )

    @property
    def assertions_skipped(self) -> int:
        """Total unchanged assertion events skipped across NIP-85 subject kinds."""
        return (
            self.user.skipped
            + self.event.skipped
            + self.addressable.skipped
            + self.identifier.skipped
        )

    @property
    def assertions_failed(self) -> int:
        """Total assertion events that failed to publish across NIP-85 subject kinds."""
        return (
            self.user.failed + self.event.failed + self.addressable.failed + self.identifier.failed
        )

    @property
    def provider_profiles_published(self) -> int:
        """Provider profile events published in this cycle."""
        return self.provider_profile.published

    @property
    def provider_profiles_skipped(self) -> int:
        """Provider profile events skipped in this cycle."""
        return self.provider_profile.skipped

    @property
    def provider_profiles_failed(self) -> int:
        """Provider profile events that failed in this cycle."""
        return self.provider_profile.failed


async def publish_timed(
    publish_func: Callable[[], Awaitable[tuple[int, int, int]]],
) -> PublishKindResult:
    """Run one publish branch and return counts plus duration."""
    phase_start = time.monotonic()
    published, skipped, failed = await publish_func()
    return PublishKindResult(
        eligible=published + skipped + failed,
        published=published,
        skipped=skipped,
        failed=failed,
        duration_seconds=time.monotonic() - phase_start,
    )


async def run_selected_publishers(  # noqa: PLR0913
    *,
    config: AssertorConfig,
    publish_timed_func: Callable[
        [Callable[[], Awaitable[tuple[int, int, int]]]],
        Awaitable[PublishKindResult],
    ],
    publish_user_assertions: Callable[[], Awaitable[tuple[int, int, int]]],
    publish_event_assertions: Callable[[], Awaitable[tuple[int, int, int]]],
    publish_addressable_assertions: Callable[[], Awaitable[tuple[int, int, int]]],
    publish_identifier_assertions: Callable[[], Awaitable[tuple[int, int, int]]],
    publish_provider_profile: Callable[[], Awaitable[tuple[int, int, int]]],
) -> tuple[
    PublishKindResult,
    PublishKindResult,
    PublishKindResult,
    PublishKindResult,
    PublishKindResult,
]:
    """Run the enabled publish branches for one assertor cycle."""
    results = {
        "user": PublishKindResult(),
        "event": PublishKindResult(),
        "addressable": PublishKindResult(),
        "identifier": PublishKindResult(),
        "provider_profile": PublishKindResult(),
    }

    selected: list[tuple[str, Callable[[], Awaitable[tuple[int, int, int]]]]] = []
    if EventKind.NIP85_USER_ASSERTION in config.selection.kinds:
        selected.append(("user", publish_user_assertions))
    if EventKind.NIP85_EVENT_ASSERTION in config.selection.kinds:
        selected.append(("event", publish_event_assertions))
    if EventKind.NIP85_ADDRESSABLE_ASSERTION in config.selection.kinds:
        selected.append(("addressable", publish_addressable_assertions))
    if EventKind.NIP85_IDENTIFIER_ASSERTION in config.selection.kinds:
        selected.append(("identifier", publish_identifier_assertions))
    if config.provider_profile.enabled:
        selected.append(("provider_profile", publish_provider_profile))

    for result_name, publish_func in selected:
        results[result_name] = await publish_timed_func(publish_func)

    return (
        results["user"],
        results["event"],
        results["addressable"],
        results["identifier"],
        results["provider_profile"],
    )


async def run_checkpoint_cleanup(
    *,
    cleanup_enabled: bool,
    delete_stale_checkpoints: Callable[[], Awaitable[int]],
) -> tuple[int, float]:
    """Remove stale checkpoints when configured and report elapsed time."""
    cleanup_start = time.monotonic()
    removed = 0
    if cleanup_enabled:
        removed = await delete_stale_checkpoints()
    return removed, time.monotonic() - cleanup_start


def emit_publish_metrics(
    service: BaseService[AssertorConfig],
    result: PublishCycleResult,
    *,
    cleanup_duration: float,
) -> None:
    """Emit aggregate and per-kind publish metrics from the cycle result."""
    service.set_gauge("assertions_published", result.assertions_published)
    service.set_gauge("assertions_skipped", result.assertions_skipped)
    service.set_gauge("assertions_failed", result.assertions_failed)
    service.set_gauge("provider_profiles_published", result.provider_profiles_published)
    service.set_gauge("provider_profiles_skipped", result.provider_profiles_skipped)
    service.set_gauge("provider_profiles_failed", result.provider_profiles_failed)
    service.set_gauge("checkpoint_cleanup_removed", result.checkpoint_cleanup_removed)
    service.set_gauge("stale_checkpoints_removed", result.checkpoint_cleanup_removed)
    service.set_gauge("phase_duration_cleanup_seconds", cleanup_duration)

    for subject_kind, kind_result in (
        ("user", result.user),
        ("event", result.event),
        ("addressable", result.addressable),
        ("identifier", result.identifier),
    ):
        service.set_gauge(f"{subject_kind}_assertions_eligible", kind_result.eligible)
        service.set_gauge(f"{subject_kind}_assertions_published", kind_result.published)
        service.set_gauge(f"{subject_kind}_assertions_skipped", kind_result.skipped)
        service.set_gauge(f"{subject_kind}_assertions_failed", kind_result.failed)
        service.set_gauge(
            f"phase_duration_{subject_kind}_seconds",
            kind_result.duration_seconds,
        )

    service.set_gauge("provider_profile_published", result.provider_profile.published)
    service.set_gauge("provider_profile_skipped", result.provider_profile.skipped)
    service.set_gauge("provider_profile_failed", result.provider_profile.failed)
    service.set_gauge(
        "phase_duration_provider_profile_seconds",
        result.provider_profile.duration_seconds,
    )
