"""Assertor service for BigBrotr.

Reads NIP-85 summary tables and publishes Trusted Assertion events
(kind 30382 for users, kind 30383 for events) to configured relays.
Only publishes when assertion tag values change (per NIP-85 spec:
"only if the contents of each event actually change").

See Also:
    [AssertorConfig][bigbrotr.services.assertor.AssertorConfig]:
        Configuration model for this service.
    [bigbrotr.nips.nip85.data][]: Assertion data models.
    [bigbrotr.nips.event_builders][]: Event builder functions.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, ClassVar

import asyncpg
from nostr_sdk import Client, RelayUrl

from bigbrotr.core.base_service import BaseService
from bigbrotr.models.constants import EventKind, ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.nips.event_builders import build_event_assertion, build_user_assertion
from bigbrotr.nips.nip85.data import EventAssertion, UserAssertion
from bigbrotr.utils.protocol import broadcast_events, create_client

from .configs import AssertorConfig
from .queries import fetch_event_rows, fetch_user_rows


if TYPE_CHECKING:
    from types import TracebackType

    from bigbrotr.core.brotr import Brotr


class Assertor(BaseService[AssertorConfig]):
    """NIP-85 Trusted Assertions publisher.

    Reads per-pubkey and per-event engagement metrics from summary tables,
    converts to NIP-85 assertion events, and publishes only when values
    change. Change detection uses SHA-256 hashes of tag values, persisted
    in ``service_state`` as publish checkpoints.

    Lifecycle:
        1. ``__aenter__``: create Nostr client, connect to relays.
        2. ``run()``: fetch stats, build assertions, publish changed.
        3. ``__aexit__``: disconnect client.

    See Also:
        [AssertorConfig][bigbrotr.services.assertor.AssertorConfig]:
            Configuration model for this service.
    """

    SERVICE_NAME: ClassVar[ServiceName] = ServiceName.ASSERTOR
    CONFIG_CLASS: ClassVar[type[AssertorConfig]] = AssertorConfig

    def __init__(self, brotr: Brotr, config: AssertorConfig | None = None) -> None:
        super().__init__(brotr=brotr, config=config)
        self._config: AssertorConfig
        self._client: Client | None = None

    async def __aenter__(self) -> Assertor:
        await super().__aenter__()

        client = await create_client(
            keys=self._config.keys, allow_insecure=self._config.allow_insecure
        )
        self._client = client

        pubkey = self._config.keys.public_key().to_hex()
        self._logger.info("client_created", pubkey=pubkey)

        for relay in self._config.relays:
            await client.add_relay(RelayUrl.parse(relay.url))
            self._logger.info("relay_added", url=relay.url)
        await client.connect()

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
        """No-op: assertion publish state does not require periodic cleanup."""
        return 0

    async def run(self) -> None:
        """Execute one assertion cycle: fetch stats, build events, publish changed."""
        if self._client is None:
            return

        published = 0
        skipped = 0
        failed = 0

        if EventKind.NIP85_USER_ASSERTION in self._config.kinds:
            p, s, f = await self._publish_user_assertions()
            published += p
            skipped += s
            failed += f

        if EventKind.NIP85_EVENT_ASSERTION in self._config.kinds:
            p, s, f = await self._publish_event_assertions()
            published += p
            skipped += s
            failed += f

        self.set_gauge("assertions_published", published)
        self.set_gauge("assertions_skipped", skipped)
        self.set_gauge("assertions_failed", failed)
        self._logger.info(
            "cycle_completed",
            published=published,
            skipped=skipped,
            failed=failed,
        )

    async def _publish_user_assertions(self) -> tuple[int, int, int]:
        """Publish kind 30382 user assertions for qualifying pubkeys."""
        published = 0
        skipped = 0
        failed = 0
        offset = 0

        while True:
            rows = await fetch_user_rows(
                self._brotr,
                self._config.min_events,
                self._config.batch_size,
                offset,
            )
            if not rows:
                break

            for row in rows:
                row["top_topics_limit"] = self._config.top_topics
                assertion = UserAssertion.from_db_row(row)
                current_hash = assertion.tags_hash()

                state_key = f"user:{assertion.pubkey}"
                if await self._is_unchanged(state_key, current_hash):
                    skipped += 1
                    continue

                try:
                    builder = build_user_assertion(assertion)
                    sent = await broadcast_events([builder], [self._client])
                    if sent > 0:
                        await self._save_hash(state_key, current_hash)
                        published += 1
                    else:
                        failed += 1
                except (asyncpg.PostgresError, OSError) as exc:
                    failed += 1
                    self._logger.error(
                        "user_assertion_failed", pubkey=assertion.pubkey, error=str(exc)
                    )

            if len(rows) < self._config.batch_size:
                break
            offset += self._config.batch_size

        return published, skipped, failed

    async def _publish_event_assertions(self) -> tuple[int, int, int]:
        """Publish kind 30383 event assertions for events with engagement."""
        published = 0
        skipped = 0
        failed = 0
        offset = 0

        while True:
            rows = await fetch_event_rows(
                self._brotr,
                self._config.batch_size,
                offset,
            )
            if not rows:
                break

            for row in rows:
                assertion = EventAssertion.from_db_row(row)
                current_hash = assertion.tags_hash()

                state_key = f"event:{assertion.event_id}"
                if await self._is_unchanged(state_key, current_hash):
                    skipped += 1
                    continue

                try:
                    builder = build_event_assertion(assertion)
                    sent = await broadcast_events([builder], [self._client])
                    if sent > 0:
                        await self._save_hash(state_key, current_hash)
                        published += 1
                    else:
                        failed += 1
                except (asyncpg.PostgresError, OSError) as exc:
                    failed += 1
                    self._logger.error(
                        "event_assertion_failed",
                        event_id=assertion.event_id,
                        error=str(exc),
                    )

            if len(rows) < self._config.batch_size:
                break
            offset += self._config.batch_size

        return published, skipped, failed

    async def _is_unchanged(self, subject: str, current_hash: str) -> bool:
        """Check if the assertion for this subject has the same hash as last published."""
        states = await self._brotr.get_service_state(
            ServiceName.ASSERTOR,
            ServiceStateType.CHECKPOINT,
            subject,
        )
        if not states:
            return False
        return states[0].state_value.get("hash") == current_hash

    async def _save_hash(self, subject: str, hash_value: str) -> None:
        """Persist the published assertion hash for change detection."""
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
