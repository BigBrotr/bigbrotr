"""NIP-90 Data Vending Machine service for Nostr read-model queries.

Listens for NIP-90 job requests on configured relays, executes
read-only queries via the shared
[Catalog][bigbrotr.services.common.catalog.Catalog], and publishes
results as job-result events (request kind + 1000). Read-model pricing via
[ReadModelPolicy][bigbrotr.services.common.configs.ReadModelPolicy]
enables the NIP-90 bid/payment-required mechanism.

Each ``run()`` cycle drains job requests buffered by a long-lived NIP-90
subscription, processes them in cursor order, and publishes results or
error feedback.

Note:
    Event IDs are deduplicated in-memory (capped at 10,000) to avoid
    processing the same job twice within the current process. A persisted
    `(timestamp, event_id)` cursor provides restart-safe replay protection
    for the long-lived subscription.

See Also:
    [DvmConfig][bigbrotr.services.dvm.DvmConfig]: Configuration model
        for relays, pricing, and NIP-90 settings.
    [Catalog][bigbrotr.services.common.catalog.Catalog]: Schema
        introspection and query builder shared with the API service.
    [BaseService][bigbrotr.core.base_service.BaseService]: Abstract
        base class providing lifecycle and metrics.

Examples:
    ```python
    from bigbrotr.core import Brotr
    from bigbrotr.services import Dvm

    brotr = Brotr.from_yaml("deployments/bigbrotr/config/brotr.yaml")
    dvm = Dvm.from_yaml("deployments/bigbrotr/config/services/dvm.yaml", brotr=brotr)

    async with brotr:
        async with dvm:
            await dvm.run_forever()
    ```
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, ClassVar

import asyncpg

from bigbrotr.core.base_service import BaseService
from bigbrotr.models.constants import ServiceName
from bigbrotr.services.common.read_models import ReadModelSurface
from bigbrotr.services.common.state_store import ServiceStateStore
from bigbrotr.services.common.types import DvmRequestCursor
from bigbrotr.utils.protocol import NostrClientManager, normalize_send_output

from .configs import DvmConfig
from .jobs import JobExecutionContext, JobRuntime, process_request_event
from .subscriptions import start_request_subscription, stop_request_subscription
from .utils import (
    build_announcement_event,
)


if TYPE_CHECKING:
    from types import TracebackType

    from nostr_sdk import Client, Keys

    from bigbrotr.core.brotr import Brotr

_MAX_PROCESSED_IDS = 10_000
_MIN_TAG_LEN = 2
_REQUEST_CURSOR_KEY = "job_requests"
_REQUEST_CURSOR_DEFAULT_ID = "0" * 64


class Dvm(BaseService[DvmConfig]):
    """NIP-90 Data Vending Machine for BigBrotr read-model queries.

    Processes NIP-90 job requests (default Kind 5050) by executing
    read-only read-model queries and publishing results (Kind 6050).
    Supports per-read-model pricing with bid/payment-required negotiation.

    Lifecycle:
        1. ``__aenter__``: discover schema, create Nostr client, connect
           to relays, optionally publish NIP-89 announcement.
        2. ``run()``: drain buffered subscription events, process each, publish results.
        3. ``__aexit__``: disconnect client.

    See Also:
        [DvmConfig][bigbrotr.services.dvm.DvmConfig]: Configuration
            model for this service.
        [Api][bigbrotr.services.api.Api]: Sibling service that exposes
            the same Catalog data via HTTP REST.
    """

    SERVICE_NAME: ClassVar[ServiceName] = ServiceName.DVM
    CONFIG_CLASS: ClassVar[type[DvmConfig]] = DvmConfig

    def __init__(self, brotr: Brotr, config: DvmConfig | None = None) -> None:
        super().__init__(brotr=brotr, config=config)
        self._config: DvmConfig
        self._read_models = ReadModelSurface(policy_source=lambda: self._config.read_models)
        self._client: Client | None = None
        self._client_manager = NostrClientManager(
            keys=self._config.keys.keys,
            allow_insecure=self._config.allow_insecure,
        )
        self._notification_task: asyncio.Task[None] | None = None
        self._request_events: asyncio.Queue[Any] | None = None
        self._request_subscription_id: str | None = None
        self._state_store = ServiceStateStore(self._brotr)
        self._keys: Keys = self._config.keys.keys
        self._last_fetch_ts: int = 0
        self._last_fetch_id: str = _REQUEST_CURSOR_DEFAULT_ID
        self._processed_ids: set[str] = set()

    async def __aenter__(self) -> Dvm:
        await super().__aenter__()
        await self._read_models.discover(self._brotr, logger=self._logger)
        keys = self._keys
        manager = self._client_manager
        session = await manager.connect_session(
            "dvm-read-relays",
            self._config.relays,
            timeout=self._config.fetch_timeout,
        )
        client = session.client
        connect_result = session.connect_result
        self._client = client

        pubkey = keys.public_key().to_hex()
        self._logger.info("client_created", pubkey=pubkey)
        for relay_url in connect_result.connected:
            self._logger.info("relay_connected", url=relay_url)
        for relay_url, error in connect_result.failed.items():
            self._logger.warning("relay_connect_failed", url=relay_url, error=error)
        if not connect_result.connected:
            await manager.disconnect()
            self._client = None
            raise TimeoutError("dvm could not connect to any relay")

        try:
            cursor = (
                await self._state_store.fetch_cursors(
                    ServiceName.DVM,
                    [_REQUEST_CURSOR_KEY],
                    DvmRequestCursor,
                )
            )[0]
            if cursor.timestamp > 0:
                self._last_fetch_ts = cursor.timestamp
                self._last_fetch_id = cursor.id
                self._logger.info(
                    "request_cursor_restored",
                    timestamp=cursor.timestamp,
                    event_id=cursor.id,
                )
            else:
                timestamp = int(time.time())
                await self._store_request_cursor(timestamp, _REQUEST_CURSOR_DEFAULT_ID)
                self._logger.info(
                    "request_cursor_initialized",
                    timestamp=timestamp,
                    event_id=_REQUEST_CURSOR_DEFAULT_ID,
                )
            await self._start_request_subscription(connect_result.connected)
            if self._config.announce:
                await self._publish_announcement()
        except (asyncpg.PostgresError, OSError, RuntimeError, TimeoutError):
            await self._stop_request_subscription()
            await manager.disconnect()
            self._client = None
            raise

        self.set_gauge("read_models_exposed", len(self._read_models.enabled_names("dvm")))

        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: TracebackType | None,
    ) -> None:
        if self._client is not None:
            await self._stop_request_subscription()
            await self._client_manager.disconnect()
            self._client = None
            self._logger.info("client_disconnected")
        await super().__aexit__(_exc_type, _exc_val, _exc_tb)

    async def cleanup(self) -> int:
        """No-op: Dvm keeps a request cursor but has no stale state cleanup."""
        return 0

    async def run(self) -> None:
        """Fetch and process NIP-90 job requests for one cycle.

        Drains the subscription buffer, processes new requests in cursor
        order, persists the newest replay boundary, then updates metrics
        and manages the dedup set size.
        """
        if self._client is None:
            return

        task = self._notification_task
        if task is not None and task.done():
            if task.cancelled():
                raise RuntimeError("dvm request subscription was cancelled unexpectedly")
            error = task.exception()
            if error is None:
                raise RuntimeError("dvm request subscription stopped unexpectedly")
            raise RuntimeError("dvm request subscription failed") from error

        events: list[Any] = []
        if self._request_events is not None:
            while True:
                try:
                    events.append(self._request_events.get_nowait())
                except asyncio.QueueEmpty:
                    break
            events.sort(key=lambda event: (event.created_at().as_secs(), event.id().to_hex()))
        if not events:
            read_models_exposed = len(self._read_models.enabled_names("dvm"))
            self.inc_counter("requests_total", 0)
            self.inc_counter("requests_failed", 0)
            self.set_gauge("read_models_exposed", read_models_exposed)
            self._logger.info(
                "cycle_stats",
                jobs_received=0,
                processed=0,
                failed=0,
                payment_required=0,
                read_models_exposed=read_models_exposed,
            )
            return

        received = 0
        processed = 0
        failed = 0
        payment_required = 0
        keys = self._keys
        pubkey_hex = keys.public_key().to_hex()
        latest_ts = self._last_fetch_ts
        latest_id = self._last_fetch_id

        for event in events:
            event_ts, event_id = event.created_at().as_secs(), event.id().to_hex()
            if (event_ts, event_id) <= (latest_ts, latest_id):
                continue
            r, p, f, pr = await self._process_event(event, pubkey_hex)
            received += r
            processed += p
            failed += f
            payment_required += pr
            latest_ts, latest_id = event_ts, event_id

        if len(self._processed_ids) >= _MAX_PROCESSED_IDS:
            self._processed_ids.clear()
        if (latest_ts, latest_id) != (self._last_fetch_ts, self._last_fetch_id):
            await self._store_request_cursor(latest_ts, latest_id)
        read_models_exposed = len(self._read_models.enabled_names("dvm"))
        self.inc_counter("requests_total", received)
        self.inc_counter("requests_failed", failed)
        self.set_gauge("read_models_exposed", read_models_exposed)
        self._logger.info(
            "cycle_stats",
            jobs_received=received,
            processed=processed,
            failed=failed,
            payment_required=payment_required,
            read_models_exposed=read_models_exposed,
        )

    # ── Event processing ──────────────────────────────────────────

    async def _process_event(
        self,
        event: Any,
        pubkey_hex: str,
    ) -> tuple[int, int, int, int]:
        """Process a single NIP-90 job request event."""
        return await process_request_event(
            event=event,
            pubkey_hex=pubkey_hex,
            processed_ids=self._processed_ids,
            runtime=JobRuntime(
                logger=self._logger,
                send_event=self._send_event,
                query_entry=self._query_read_model,
            ),
            context=JobExecutionContext(
                policies=self._config.read_models,
                available_catalog_names=set(self._read_models.catalog.tables),
                default_page_size=self._config.default_page_size,
                max_page_size=self._config.max_page_size,
                request_kind=self._config.kind,
            ),
        )

    # ── Read-model policy helpers ─────────────────────────────────

    # ── Event fetching ────────────────────────────────────────────

    async def _store_request_cursor(self, timestamp: int, event_id: str) -> None:
        """Persist the current request cursor after a successful cycle."""
        self._last_fetch_ts = timestamp
        self._last_fetch_id = event_id
        await self._state_store.upsert_cursors(
            ServiceName.DVM,
            [
                DvmRequestCursor(
                    key=_REQUEST_CURSOR_KEY,
                    timestamp=timestamp,
                    id=event_id,
                )
            ],
        )

    async def _start_request_subscription(self, connected_relays: tuple[str, ...]) -> None:
        """Subscribe the DVM client to long-lived job request notifications."""
        if self._client is None:
            return
        subscription = await start_request_subscription(
            client=self._client,
            connected_relays=connected_relays,
            kind=self._config.kind,
            since=self._last_fetch_ts,
            logger=self._logger,
        )
        self._request_events = subscription.queue
        self._request_subscription_id = subscription.subscription_id
        self._notification_task = subscription.task

    async def _stop_request_subscription(self) -> None:
        """Stop the long-lived DVM request subscription notification loop."""
        task = self._notification_task
        self._notification_task = None
        self._request_events = None
        self._request_subscription_id = None
        await stop_request_subscription(task, logger=self._logger)

    # ── Event publishing ──────────────────────────────────────────

    async def _query_read_model(self, read_model: Any, query: Any) -> Any:
        """Execute one resolved read-model query through the shared surface."""
        return await self._read_models.query_entry(self._brotr, read_model, query)

    async def _send_event(
        self,
        builder: Any,
        *,
        require_success: bool = False,
    ) -> tuple[tuple[str, ...], dict[str, str]]:
        """Sign and send an event via the connected client.

        No-op if the client is not connected.
        """
        if self._client is None:
            return (), {}

        output = await self._client.send_event_builder(builder)
        successful_relays, failed_relays = normalize_send_output(output)

        if require_success and not successful_relays:
            raise OSError("event was not accepted by any relay")

        return successful_relays, failed_relays

    async def _publish_announcement(self) -> None:
        """Publish a NIP-89 handler announcement (kind 31990)."""
        if self._client is None:
            return

        read_models = self._read_models.enabled_names("dvm")
        builder = build_announcement_event(
            d_tag=self._config.d_tag,
            kind=self._config.kind,
            name=self._config.name,
            about=self._config.about,
            read_models=read_models,
        )
        successful_relays, failed_relays = await self._send_event(builder)
        if successful_relays:
            self._logger.info(
                "announcement_published",
                kind=31990,
                relays=len(successful_relays),
            )
            return

        self._logger.warning(
            "announcement_publish_failed",
            kind=31990,
            error="no relays accepted announcement",
            failed_relays=failed_relays,
        )
