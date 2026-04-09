"""Assertor service for BigBrotr.

Reads NIP-85 facts and rank snapshots and publishes Trusted Assertion events
(kinds 30382-30385). Phase 3 introduces the
algorithm-aware v2 runtime contract:

- change detection keys are versioned as ``v2:<algorithm_id>:<kind>:<subject_id>``
- legacy ``user:`` / ``event:`` checkpoints are purged automatically
- provider profile publishing for the service key is optional and content-based
- stale v2 checkpoints are removed when subjects are no longer eligible
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

import asyncpg
from nostr_sdk import Client, RelayUrl

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
from bigbrotr.utils.protocol import broadcast_events, create_client

from .configs import AssertorConfig
from .queries import (
    fetch_addressable_rows,
    fetch_event_rows,
    fetch_identifier_rows,
    fetch_user_rows,
)


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from types import TracebackType

    from nostr_sdk import EventBuilder, Keys

    from bigbrotr.core.brotr import Brotr


_LEGACY_CHECKPOINT_PREFIXES = ("user:", "event:")
_PROFILE_SUBJECT_ID = "provider_profile"
_V2_CHECKPOINT_PARTS = 4


@dataclass(frozen=True, slots=True)
class PublishCycleResult:
    """Outcome of one assertor publish cycle."""

    assertions_published: int = 0
    assertions_skipped: int = 0
    assertions_failed: int = 0
    provider_profiles_published: int = 0
    provider_profiles_skipped: int = 0
    provider_profiles_failed: int = 0
    checkpoint_cleanup_removed: int = 0


@dataclass(frozen=True, slots=True)
class _PublishPlan:
    """One assertion publish flow bound to a specific NIP-85 subject kind."""

    kind: int
    fetch_rows: Callable[[int], Awaitable[list[dict[str, Any]]]]
    assertion_from_row: Callable[[dict[str, Any]], Any]
    subject_getter: Callable[[Any], str]
    builder_from_assertion: Callable[[Any], EventBuilder]
    error_event_name: str
    error_subject_field: str


class Assertor(BaseService[AssertorConfig]):
    """NIP-85 Trusted Assertions publisher."""

    SERVICE_NAME: ClassVar[ServiceName] = ServiceName.ASSERTOR
    CONFIG_CLASS: ClassVar[type[AssertorConfig]] = AssertorConfig

    def __init__(self, brotr: Brotr, config: AssertorConfig | None = None) -> None:
        super().__init__(brotr=brotr, config=config)
        self._config: AssertorConfig
        self._client: Client | None = None
        self._keys: Keys = self._config.keys.keys
        self._cycle_seen_state_keys: set[str] = set()

    async def __aenter__(self) -> Assertor:
        await super().__aenter__()
        keys = self._keys

        client = await create_client(
            keys=keys,
            allow_insecure=self._config.publishing.allow_insecure,
        )
        self._client = client

        pubkey = keys.public_key().to_hex()
        self._logger.info(
            "client_created",
            pubkey=pubkey,
            algorithm_id=self._config.algorithm_id,
        )

        for relay in self._config.publishing.relays:
            await client.add_relay(RelayUrl.parse(relay.url))
            self._logger.info("relay_added", url=relay.url)
        await client.connect()

        removed = 0
        if self._config.cleanup.remove_legacy_checkpoints:
            removed = await self._purge_legacy_checkpoints()
        self._logger.info(
            "legacy_checkpoint_cleanup_completed",
            removed=removed,
            algorithm_id=self._config.algorithm_id,
        )

        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: TracebackType | None,
    ) -> None:
        if self._client is not None:
            from bigbrotr.utils.protocol import shutdown_client  # noqa: PLC0415

            await shutdown_client(self._client)
            self._client = None
            self._logger.info("client_disconnected")
        await super().__aexit__(_exc_type, _exc_val, _exc_tb)

    async def cleanup(self) -> int:
        """No-op: post-run checkpoint cleanup depends on current eligible subjects."""
        return 0

    async def run(self) -> None:
        """Execute one assertion cycle in algorithm-aware v2 mode."""
        await self.publish()

    async def publish(self) -> PublishCycleResult:
        """Publish one algorithm-aware NIP-85 assertion cycle."""
        if self._client is None:
            return PublishCycleResult()

        self._cycle_seen_state_keys = set()

        published = 0
        skipped = 0
        failed = 0
        profile_published = 0
        profile_skipped = 0
        profile_failed = 0

        if EventKind.NIP85_USER_ASSERTION in self._config.selection.kinds:
            p, s, f = await self._publish_user_assertions()
            published += p
            skipped += s
            failed += f

        if EventKind.NIP85_EVENT_ASSERTION in self._config.selection.kinds:
            p, s, f = await self._publish_event_assertions()
            published += p
            skipped += s
            failed += f

        if EventKind.NIP85_ADDRESSABLE_ASSERTION in self._config.selection.kinds:
            p, s, f = await self._publish_addressable_assertions()
            published += p
            skipped += s
            failed += f

        if EventKind.NIP85_IDENTIFIER_ASSERTION in self._config.selection.kinds:
            p, s, f = await self._publish_identifier_assertions()
            published += p
            skipped += s
            failed += f

        if self._provider_profile_enabled():
            (
                profile_published,
                profile_skipped,
                profile_failed,
            ) = await self._publish_provider_profile()

        removed = 0
        if self._config.cleanup.remove_stale_checkpoints:
            removed = await self._delete_stale_v2_checkpoints()

        self.set_gauge("assertions_published", published)
        self.set_gauge("assertions_skipped", skipped)
        self.set_gauge("assertions_failed", failed)
        self.set_gauge("provider_profiles_published", profile_published)
        self.set_gauge("provider_profiles_skipped", profile_skipped)
        self.set_gauge("provider_profiles_failed", profile_failed)
        self.set_gauge("checkpoint_cleanup_removed", removed)
        self._logger.info(
            "cycle_completed",
            algorithm_id=self._config.algorithm_id,
            published=published,
            skipped=skipped,
            failed=failed,
            provider_profiles_published=profile_published,
            provider_profiles_skipped=profile_skipped,
            provider_profiles_failed=profile_failed,
            checkpoints_removed=removed,
        )

        return PublishCycleResult(
            assertions_published=published,
            assertions_skipped=skipped,
            assertions_failed=failed,
            provider_profiles_published=profile_published,
            provider_profiles_skipped=profile_skipped,
            provider_profiles_failed=profile_failed,
            checkpoint_cleanup_removed=removed,
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
            _PublishPlan(
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
            _PublishPlan(
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
            _PublishPlan(
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
            _PublishPlan(
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
        plan: _PublishPlan,
    ) -> tuple[int, int, int]:
        """Publish one assertion subject type using the shared v2 change-detection flow."""
        published = 0
        skipped = 0
        failed = 0
        offset = 0

        while True:
            rows = await plan.fetch_rows(offset)
            if not rows:
                break

            for row in rows:
                assertion = plan.assertion_from_row(row)
                subject_id = plan.subject_getter(assertion)
                state_key = self._state_key(plan.kind, subject_id)
                self._mark_seen_state_key(state_key)
                current_hash = assertion.tags_hash()

                if await self._is_unchanged(state_key, current_hash):
                    skipped += 1
                    continue

                try:
                    builder = plan.builder_from_assertion(assertion)
                    sent = await broadcast_events([builder], [self._client])
                    if sent > 0:
                        await self._save_hash(state_key, current_hash)
                        published += 1
                    else:
                        failed += 1
                except (asyncpg.PostgresError, OSError) as exc:
                    failed += 1
                    self._logger.error(
                        plan.error_event_name,
                        **{
                            plan.error_subject_field: subject_id,
                            "algorithm_id": self._config.algorithm_id,
                            "error": str(exc),
                        },
                    )

            if len(rows) < self._config.selection.batch_size:
                break
            offset += self._config.selection.batch_size

        return published, skipped, failed

    async def _publish_provider_profile(self) -> tuple[int, int, int]:
        """Publish the optional Kind 0 provider profile when its content changes."""
        state_key = self._state_key(EventKind.SET_METADATA, _PROFILE_SUBJECT_ID)
        self._mark_seen_state_key(state_key)

        content = self._provider_profile_content()
        current_hash = self._content_hash(content)
        if await self._is_unchanged(state_key, current_hash):
            return 0, 1, 0

        kind0 = self._config.provider_profile.kind0_content
        extra_fields = {
            "algorithm_id": self._config.algorithm_id,
            **{
                key: value
                for key, value in kind0.extra_fields.items()
                if value is not None and key != "algorithm_id"
            },
        }

        try:
            builder = build_profile_event(
                name=kind0.name,
                about=kind0.about,
                picture=kind0.picture,
                nip05=kind0.nip05,
                website=kind0.website,
                banner=kind0.banner,
                lud16=kind0.lud16,
                extra_fields=extra_fields,
            )
            sent = await broadcast_events([builder], [self._client])
            if sent > 0:
                await self._save_hash(state_key, current_hash)
                self._logger.info(
                    "provider_profile_published",
                    algorithm_id=self._config.algorithm_id,
                    relays=sent,
                )
                return 1, 0, 0

            self._logger.warning(
                "provider_profile_publish_failed",
                algorithm_id=self._config.algorithm_id,
                error="no relays reachable",
            )
            return 0, 0, 1
        except (asyncpg.PostgresError, OSError) as exc:
            self._logger.error(
                "provider_profile_publish_failed",
                algorithm_id=self._config.algorithm_id,
                error=str(exc),
            )
            return 0, 0, 1

    def _provider_profile_content(self) -> dict[str, Any]:
        """Return the effective Kind 0 content for the provider profile."""
        cfg = self._config.provider_profile.kind0_content
        content: dict[str, Any] = {
            "name": cfg.name,
            "about": cfg.about,
            "website": cfg.website,
            "algorithm_id": self._config.algorithm_id,
        }

        optional_fields = {
            "picture": cfg.picture,
            "nip05": cfg.nip05,
            "banner": cfg.banner,
            "lud16": cfg.lud16,
        }
        content.update({key: value for key, value in optional_fields.items() if value is not None})

        for key, value in cfg.extra_fields.items():
            if key and value is not None and key not in content:
                content[key] = value

        return content

    def _content_hash(self, content: dict[str, Any]) -> str:
        """Compute a stable SHA-256 hash for JSON profile content."""
        return hashlib.sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def _state_key(self, kind: int, subject_id: str) -> str:
        """Build the v2 checkpoint key for one algorithm/kind/subject tuple."""
        return f"v2:{self._config.algorithm_id}:{int(kind)}:{subject_id}"

    def _mark_seen_state_key(self, state_key: str) -> None:
        """Track checkpoints that were still eligible in the current cycle."""
        if not hasattr(self, "_cycle_seen_state_keys"):
            self._cycle_seen_state_keys = set()
        self._cycle_seen_state_keys.add(state_key)

    def _provider_profile_enabled(self) -> bool:
        """Return whether Kind 0 provider profile publishing is explicitly enabled."""
        enabled = getattr(getattr(self._config, "provider_profile", None), "enabled", False)
        return enabled if isinstance(enabled, bool) else False

    async def _purge_legacy_checkpoints(self) -> int:
        """Delete legacy pre-v2 assertor checkpoints once at service startup."""
        states = await self._brotr.get_service_state(
            ServiceName.ASSERTOR,
            ServiceStateType.CHECKPOINT,
        )
        stale = [
            state for state in states if state.state_key.startswith(_LEGACY_CHECKPOINT_PREFIXES)
        ]
        if not stale:
            return 0

        return await self._brotr.delete_service_state(
            service_names=[state.service_name for state in stale],
            state_types=[state.state_type for state in stale],
            state_keys=[state.state_key for state in stale],
        )

    async def _delete_stale_v2_checkpoints(self) -> int:
        """Delete current-algorithm v2 checkpoints whose subjects are no longer eligible."""
        states = await self._brotr.get_service_state(
            ServiceName.ASSERTOR,
            ServiceStateType.CHECKPOINT,
        )
        configured_kinds = {int(kind) for kind in self._config.selection.kinds}
        if self._provider_profile_enabled():
            configured_kinds.add(int(EventKind.SET_METADATA))

        stale: list[ServiceState] = []
        for state in states:
            parsed = self._parse_v2_checkpoint_key(state.state_key)
            if parsed is None:
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

    def _parse_v2_checkpoint_key(self, state_key: str) -> tuple[str, int, str] | None:
        """Parse ``v2:<algorithm_id>:<kind>:<subject_id>`` keys.

        ``subject_id`` may itself contain ``:`` characters, so parsing stops after
        the first three separators.
        """
        parts = state_key.split(":", 3)
        if len(parts) != _V2_CHECKPOINT_PARTS or parts[0] != "v2":
            return None
        try:
            kind = int(parts[2])
        except ValueError:
            return None
        return parts[1], kind, parts[3]

    async def _is_unchanged(self, subject: str, current_hash: str) -> bool:
        """Check if the assertion/profile for this subject has the same hash as last published."""
        states = await self._brotr.get_service_state(
            ServiceName.ASSERTOR,
            ServiceStateType.CHECKPOINT,
            subject,
        )
        if not states:
            return False
        return states[0].state_value.get("hash") == current_hash

    async def _save_hash(self, subject: str, hash_value: str) -> None:
        """Persist the published object hash for change detection."""
        await self._brotr.upsert_service_state(
            [
                ServiceState(
                    service_name=ServiceName.ASSERTOR,
                    state_type=ServiceStateType.CHECKPOINT,
                    state_key=subject,
                    state_value={"hash": hash_value, "timestamp": int(time.time())},
                )
            ]
        )
