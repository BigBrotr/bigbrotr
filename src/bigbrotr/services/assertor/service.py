"""Assertor service for BigBrotr.

Reads NIP-85 facts and rank snapshots and publishes Trusted Assertion events
(kinds 30382-30385). Change detection uses canonical
``<algorithm_id>:<kind>:<subject_id>`` checkpoint keys, provider profile
publishing is optional and content-based, and stale checkpoints are removed
when subjects are no longer eligible.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

from bigbrotr.core.base_service import BaseService
from bigbrotr.models.constants import EventKind, ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.nips.event_builders import (
    build_addressable_assertion,
    build_event_assertion,
    build_identifier_assertion,
    build_profile_event,
    build_user_assertion,
)
from bigbrotr.nips.nip85.data import (
    AddressableAssertion,
    EventAssertion,
    IdentifierAssertion,
    UserAssertion,
)
from bigbrotr.services.common.state_store import ServiceStateStore
from bigbrotr.utils.protocol import NostrClientManager, broadcast_events
from bigbrotr.utils.transport import DEFAULT_TIMEOUT

from .configs import AssertorConfig
from .publishing import (
    ProviderProfileRuntime,
    PublishPlan,
    PublishRuntime,
    publish_assertion_rows,
    publish_provider_profile,
)
from .queries import (
    fetch_addressable_rows,
    fetch_event_rows,
    fetch_identifier_rows,
    fetch_user_rows,
)
from .utils import (
    build_state_key,
    content_hash,
    parse_state_key,
    provider_profile_content,
)


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from types import TracebackType

    from nostr_sdk import Client, Keys

    from bigbrotr.core.brotr import Brotr


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


class Assertor(BaseService[AssertorConfig]):
    """NIP-85 Trusted Assertions publisher."""

    SERVICE_NAME: ClassVar[ServiceName] = ServiceName.ASSERTOR
    CONFIG_CLASS: ClassVar[type[AssertorConfig]] = AssertorConfig

    def __init__(self, brotr: Brotr, config: AssertorConfig | None = None) -> None:
        super().__init__(brotr=brotr, config=config)
        self._config: AssertorConfig
        self._client: Client | None = None
        self._client_manager: NostrClientManager | None = None
        self._keys: Keys = self._config.keys.keys
        self._cycle_seen_state_keys: set[str] = set()

    async def __aenter__(self) -> Assertor:
        await super().__aenter__()
        keys = self._keys
        manager = self._get_client_manager()
        session = await manager.connect_session(
            "assertor-publish-relays",
            self._config.publishing.relays,
            timeout=DEFAULT_TIMEOUT,
        )
        client = session.client
        connect_result = session.connect_result
        self._client = client

        pubkey = keys.public_key().to_hex()
        self._logger.info(
            "client_created",
            pubkey=pubkey,
            algorithm_id=self._config.algorithm_id,
        )
        self._logger.info(
            "client_connected",
            relays_connected=len(connect_result.connected),
            relays_failed=len(connect_result.failed),
        )
        for relay_url, error in connect_result.failed.items():
            self._logger.warning("relay_connect_failed", url=relay_url, error=error)
        if not connect_result.connected:
            await manager.disconnect()
            self._client = None
            raise TimeoutError("assertor could not connect to any publishing relay")

        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: TracebackType | None,
    ) -> None:
        if self._client is not None:
            manager = self._client_manager
            if manager is not None:
                await manager.disconnect()
            self._client = None
            self._logger.info("client_disconnected")
        await super().__aexit__(_exc_type, _exc_val, _exc_tb)

    async def cleanup(self) -> int:
        """No-op: post-run checkpoint cleanup depends on current eligible subjects."""
        return 0

    def _get_client_manager(self) -> NostrClientManager:
        """Return the lazy-initialized nostr client manager for this service."""
        manager = getattr(self, "_client_manager", None)
        if manager is None:
            manager = NostrClientManager(
                keys=self._keys,
                allow_insecure=self._config.publishing.allow_insecure,
            )
            self._client_manager = manager
        return manager

    async def run(self) -> None:
        """Execute one assertion cycle."""
        await self.publish()

    async def publish(self) -> PublishCycleResult:
        """Publish one algorithm-aware NIP-85 assertion cycle."""
        if self._client is None:
            return PublishCycleResult()

        self._cycle_seen_state_keys = set()

        user_result = PublishKindResult()
        event_result = PublishKindResult()
        addressable_result = PublishKindResult()
        identifier_result = PublishKindResult()
        provider_profile_result = PublishKindResult()

        if EventKind.NIP85_USER_ASSERTION in self._config.selection.kinds:
            user_result = await self._publish_timed(self._publish_user_assertions)

        if EventKind.NIP85_EVENT_ASSERTION in self._config.selection.kinds:
            event_result = await self._publish_timed(self._publish_event_assertions)

        if EventKind.NIP85_ADDRESSABLE_ASSERTION in self._config.selection.kinds:
            addressable_result = await self._publish_timed(self._publish_addressable_assertions)

        if EventKind.NIP85_IDENTIFIER_ASSERTION in self._config.selection.kinds:
            identifier_result = await self._publish_timed(self._publish_identifier_assertions)

        if self._provider_profile_enabled():
            provider_profile_result = await self._publish_timed(self._publish_provider_profile)

        cleanup_start = time.monotonic()
        removed = 0
        if self._config.cleanup.remove_stale_checkpoints:
            removed = await self._delete_stale_checkpoints()
        cleanup_duration = time.monotonic() - cleanup_start

        result = PublishCycleResult(
            user=user_result,
            event=event_result,
            addressable=addressable_result,
            identifier=identifier_result,
            provider_profile=provider_profile_result,
            checkpoint_cleanup_removed=removed,
        )
        self._emit_publish_metrics(result, cleanup_duration=cleanup_duration)
        self._logger.info(
            "cycle_completed",
            algorithm_id=self._config.algorithm_id,
            published=result.assertions_published,
            skipped=result.assertions_skipped,
            failed=result.assertions_failed,
            provider_profiles_published=result.provider_profiles_published,
            provider_profiles_skipped=result.provider_profiles_skipped,
            provider_profiles_failed=result.provider_profiles_failed,
            checkpoints_removed=result.checkpoint_cleanup_removed,
        )

        return result

    async def _publish_timed(
        self,
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

    def _emit_publish_metrics(
        self,
        result: PublishCycleResult,
        *,
        cleanup_duration: float,
    ) -> None:
        """Emit aggregate and per-kind publish metrics from the cycle result."""
        self.set_gauge("assertions_published", result.assertions_published)
        self.set_gauge("assertions_skipped", result.assertions_skipped)
        self.set_gauge("assertions_failed", result.assertions_failed)
        self.set_gauge("provider_profiles_published", result.provider_profiles_published)
        self.set_gauge("provider_profiles_skipped", result.provider_profiles_skipped)
        self.set_gauge("provider_profiles_failed", result.provider_profiles_failed)
        self.set_gauge("checkpoint_cleanup_removed", result.checkpoint_cleanup_removed)
        self.set_gauge("stale_checkpoints_removed", result.checkpoint_cleanup_removed)
        self.set_gauge("phase_duration_cleanup_seconds", cleanup_duration)

        for subject_kind, kind_result in (
            ("user", result.user),
            ("event", result.event),
            ("addressable", result.addressable),
            ("identifier", result.identifier),
        ):
            self.set_gauge(f"{subject_kind}_assertions_eligible", kind_result.eligible)
            self.set_gauge(f"{subject_kind}_assertions_published", kind_result.published)
            self.set_gauge(f"{subject_kind}_assertions_skipped", kind_result.skipped)
            self.set_gauge(f"{subject_kind}_assertions_failed", kind_result.failed)
            self.set_gauge(
                f"phase_duration_{subject_kind}_seconds",
                kind_result.duration_seconds,
            )

        self.set_gauge("provider_profile_published", result.provider_profile.published)
        self.set_gauge("provider_profile_skipped", result.provider_profile.skipped)
        self.set_gauge("provider_profile_failed", result.provider_profile.failed)
        self.set_gauge(
            "phase_duration_provider_profile_seconds",
            result.provider_profile.duration_seconds,
        )

    async def _publish_user_assertions(self) -> tuple[int, int, int]:
        """Publish kind 30382 user assertions for qualifying pubkeys."""

        async def _fetch(offset: int) -> list[dict[str, Any]]:
            rows = await fetch_user_rows(
                self._brotr,
                self._config.algorithm_id,
                self._config.selection.min_events,
                self._config.selection.batch_size,
                offset,
            )
            for row in rows:
                row["top_topics_limit"] = self._config.selection.top_topics
            return rows

        return await self._publish_assertion_rows(
            PublishPlan(
                kind=EventKind.NIP85_USER_ASSERTION,
                fetch_rows=_fetch,
                assertion_from_row=UserAssertion.from_db_row,
                subject_getter=lambda assertion: assertion.pubkey,
                builder_from_assertion=build_user_assertion,
                error_event_name="user_assertion_failed",
                error_subject_field="pubkey",
            )
        )

    async def _publish_event_assertions(self) -> tuple[int, int, int]:
        """Publish kind 30383 event assertions for events with engagement."""
        return await self._publish_assertion_rows(
            PublishPlan(
                kind=EventKind.NIP85_EVENT_ASSERTION,
                fetch_rows=lambda offset: fetch_event_rows(
                    self._brotr,
                    self._config.algorithm_id,
                    self._config.selection.batch_size,
                    offset,
                ),
                assertion_from_row=EventAssertion.from_db_row,
                subject_getter=lambda assertion: assertion.event_id,
                builder_from_assertion=build_event_assertion,
                error_event_name="event_assertion_failed",
                error_subject_field="event_id",
            ),
        )

    async def _publish_addressable_assertions(self) -> tuple[int, int, int]:
        """Publish kind 30384 addressable assertions for ranked addressable subjects."""
        return await self._publish_assertion_rows(
            PublishPlan(
                kind=EventKind.NIP85_ADDRESSABLE_ASSERTION,
                fetch_rows=lambda offset: fetch_addressable_rows(
                    self._brotr,
                    self._config.algorithm_id,
                    self._config.selection.batch_size,
                    offset,
                ),
                assertion_from_row=AddressableAssertion.from_db_row,
                subject_getter=lambda assertion: assertion.event_address,
                builder_from_assertion=build_addressable_assertion,
                error_event_name="addressable_assertion_failed",
                error_subject_field="event_address",
            ),
        )

    async def _publish_identifier_assertions(self) -> tuple[int, int, int]:
        """Publish kind 30385 identifier assertions for ranked NIP-73 subjects."""
        return await self._publish_assertion_rows(
            PublishPlan(
                kind=EventKind.NIP85_IDENTIFIER_ASSERTION,
                fetch_rows=lambda offset: fetch_identifier_rows(
                    self._brotr,
                    self._config.algorithm_id,
                    self._config.selection.batch_size,
                    offset,
                ),
                assertion_from_row=IdentifierAssertion.from_db_row,
                subject_getter=lambda assertion: assertion.identifier,
                builder_from_assertion=build_identifier_assertion,
                error_event_name="identifier_assertion_failed",
                error_subject_field="identifier",
            ),
        )

    async def _publish_assertion_rows(
        self,
        plan: PublishPlan[Any],
    ) -> tuple[int, int, int]:
        """Publish one assertion subject type using the shared change-detection flow."""
        if self._client is None:
            return 0, 0, 0

        return await publish_assertion_rows(
            plan,
            PublishRuntime(
                algorithm_id=self._config.algorithm_id,
                batch_size=self._config.selection.batch_size,
                client=self._client,
                logger=self._logger,
                mark_seen_state_key=self._mark_seen_state_key,
                is_unchanged=self._is_unchanged,
                save_hash=self._save_hash,
                publish_events=broadcast_events,
                build_state_key=build_state_key,
            ),
        )

    async def _publish_provider_profile(self) -> tuple[int, int, int]:
        """Publish the optional Kind 0 provider profile when its content changes."""
        if self._client is None:
            return 0, 0, 0

        return await publish_provider_profile(
            ProviderProfileRuntime(
                config=self._config,
                client=self._client,
                logger=self._logger,
                mark_seen_state_key=self._mark_seen_state_key,
                is_unchanged=self._is_unchanged,
                save_hash=self._save_hash,
                publish_events=broadcast_events,
                build_state_key=build_state_key,
                build_profile_event=build_profile_event,
                provider_profile_content=provider_profile_content,
                content_hash=content_hash,
            )
        )

    def _mark_seen_state_key(self, state_key: str) -> None:
        """Track checkpoints that were still eligible in the current cycle."""
        if not hasattr(self, "_cycle_seen_state_keys"):
            self._cycle_seen_state_keys = set()
        self._cycle_seen_state_keys.add(state_key)

    def _provider_profile_enabled(self) -> bool:
        """Return whether Kind 0 provider profile publishing is explicitly enabled."""
        enabled = getattr(getattr(self._config, "provider_profile", None), "enabled", False)
        return enabled if isinstance(enabled, bool) else False

    async def _delete_stale_checkpoints(self) -> int:
        """Delete non-canonical or current-algorithm checkpoints that are no longer eligible."""
        states = await self._brotr.get_service_state(
            ServiceName.ASSERTOR,
            ServiceStateType.CHECKPOINT,
        )
        configured_kinds = {int(kind) for kind in self._config.selection.kinds}
        if self._provider_profile_enabled():
            configured_kinds.add(int(EventKind.SET_METADATA))

        stale: list[ServiceState] = []
        for state in states:
            parsed = parse_state_key(state.state_key)
            if parsed is None:
                stale.append(state)
                continue

            algorithm_id, kind, _subject_id = parsed
            if algorithm_id != self._config.algorithm_id:
                continue
            if kind not in configured_kinds or state.state_key not in self._cycle_seen_state_keys:
                stale.append(state)

        if not stale:
            return 0

        deleted = await self._brotr.delete_service_state(
            service_names=[state.service_name for state in stale],
            state_types=[state.state_type for state in stale],
            state_keys=[state.state_key for state in stale],
        )
        self._logger.info(
            "stale_checkpoint_cleanup_completed",
            removed=deleted,
            algorithm_id=self._config.algorithm_id,
        )
        return deleted

    async def _is_unchanged(self, subject: str, current_hash: str) -> bool:
        """Check if the assertion/profile for this subject has the same hash as last published."""
        saved_hash = await ServiceStateStore(self._brotr).fetch_hash(ServiceName.ASSERTOR, subject)
        return saved_hash == current_hash

    async def _save_hash(self, subject: str, hash_value: str) -> None:
        """Persist the published object hash for change detection."""
        await ServiceStateStore(self._brotr).upsert_hash(
            ServiceName.ASSERTOR,
            subject,
            hash_value,
            timestamp=int(time.time()),
        )
