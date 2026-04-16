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
import contextlib
import time
from typing import TYPE_CHECKING, Any, ClassVar

import asyncpg
from nostr_sdk import Client, Filter, Kind, RelayUrl, Timestamp

from bigbrotr.core.base_service import BaseService
from bigbrotr.models.constants import ServiceName
from bigbrotr.services.common.catalog import CatalogError
from bigbrotr.services.common.read_models import ReadModelSurface
from bigbrotr.services.common.state_store import ServiceStateStore
from bigbrotr.services.common.types import DvmRequestCursor
from bigbrotr.utils.protocol import NostrClientManager, normalize_send_output

from .configs import DvmConfig
from .utils import (
    JobPreparationContext,
    RejectedJobRequest,
    ResultEventRequest,
    build_announcement_event,
    build_error_event,
    build_payment_required_event,
    build_result_event,
    parse_job_params,
    prepare_job_request,
)


if TYPE_CHECKING:
    from types import TracebackType

    from nostr_sdk import Keys

    from bigbrotr.core.brotr import Brotr

_MAX_PROCESSED_IDS = 10_000
_MIN_TAG_LEN = 2
_REQUEST_CURSOR_KEY = "job_requests"
_REQUEST_CURSOR_DEFAULT_ID = "0" * 64


class _RequestNotificationBuffer:
    """Buffer long-lived DVM subscription notifications into an asyncio queue."""

    __slots__ = ("_logger", "_loop", "_queue", "_subscription_id")

    def __init__(
        self,
        *,
        subscription_id: str,
        queue: asyncio.Queue[Any],
        logger: Any,
    ) -> None:
        self._subscription_id = subscription_id
        self._queue = queue
        self._loop = asyncio.get_running_loop()
        self._logger = logger

    def handle_msg(self, relay_url: RelayUrl, msg: Any) -> None:
        relay_msg = msg.as_enum()
        relay = str(relay_url)

        if (
            relay_msg.is_END_OF_STORED_EVENTS()
            and relay_msg.subscription_id == self._subscription_id
        ):
            self._logger.debug(
                "request_subscription_eose",
                relay=relay,
                subscription_id=relay_msg.subscription_id,
            )
        elif relay_msg.is_CLOSED() and relay_msg.subscription_id == self._subscription_id:
            self._logger.warning(
                "request_subscription_closed",
                relay=relay,
                subscription_id=relay_msg.subscription_id,
                message=relay_msg.message,
            )
        elif relay_msg.is_NOTICE():
            self._logger.debug(
                "request_subscription_notice",
                relay=relay,
                message=relay_msg.message,
            )

    def handle(self, _relay_url: RelayUrl, subscription_id: str, event: Any) -> None:
        if subscription_id != self._subscription_id or self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(self._queue.put_nowait, event)


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
            self._last_fetch_ts, self._last_fetch_id = await self._restore_request_cursor()
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

    def _ensure_request_subscription_healthy(self) -> None:
        """Raise if the background notification loop has stopped unexpectedly."""
        task = self._notification_task
        if task is None or not task.done():
            return

        if task.cancelled():
            raise RuntimeError("dvm request subscription was cancelled unexpectedly")
        error = task.exception()
        if error is None:
            raise RuntimeError("dvm request subscription stopped unexpectedly")
        raise RuntimeError("dvm request subscription failed") from error

    async def run(self) -> None:
        """Fetch and process NIP-90 job requests for one cycle.

        Drains the subscription buffer, processes new requests in cursor
        order, persists the newest replay boundary, then updates metrics
        and manages the dedup set size.
        """
        if self._client is None:
            return

        self._ensure_request_subscription_healthy()
        events = await self._fetch_job_requests()
        if not events:
            self._report_metrics(0, 0, 0, 0)
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
            event_ts, event_id = self._event_position(event)
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
        self._report_metrics(received, processed, failed, payment_required)

    # ── Event processing ──────────────────────────────────────────

    async def _process_event(
        self,
        event: Any,
        pubkey_hex: str,
    ) -> tuple[int, int, int, int]:
        """Process a single NIP-90 job request event.

        Returns:
            Tuple of (received, processed, failed, payment_required) deltas.
        """
        event_id = event.id().to_hex()

        if event_id in self._processed_ids:
            return 0, 0, 0, 0

        # Check p-tag targets us (cache as_vec to avoid repeated FFI calls)
        p_tags: list[str] = []
        for tag in event.tags().to_vec():
            values = tag.as_vec()
            if len(values) >= _MIN_TAG_LEN and values[0] == "p":
                p_tags.append(values[1])
        if p_tags and pubkey_hex not in p_tags:
            return 0, 0, 0, 0

        self._processed_ids.add(event_id)

        customer_pubkey = event.author().to_hex()
        params = parse_job_params(event)
        raw_read_model_id = params.get("read_model", "")
        read_model_id = raw_read_model_id

        self._logger.info(
            "job_received",
            event_id=event_id,
            read_model=read_model_id,
            raw_read_model=raw_read_model_id,
            customer=customer_pubkey,
        )

        try:
            return await self._handle_job(event_id, customer_pubkey, params, read_model_id)
        except (CatalogError, OSError, TimeoutError, asyncpg.PostgresError) as e:
            with contextlib.suppress(OSError, TimeoutError):
                await self._send_event(
                    build_error_event(event_id, customer_pubkey, str(e)),
                    require_success=True,
                )
            self._logger.error("job_failed", event_id=event_id, error=str(e))
            return 1, 0, 1, 0

    async def _handle_job(
        self,
        event_id: str,
        customer_pubkey: str,
        params: dict[str, Any],
        read_model_id: str,
    ) -> tuple[int, int, int, int]:
        """Handle a validated job request: check access, pricing, execute query.

        Returns:
            Tuple of (received, processed, failed, payment_required) deltas.
        """
        prepared_job = prepare_job_request(
            read_model_id,
            params,
            context=JobPreparationContext(
                policies=self._config.read_models,
                available_catalog_names=set(self._read_models.catalog.tables),
                default_page_size=self._config.default_page_size,
                max_page_size=self._config.max_page_size,
            ),
        )
        if isinstance(prepared_job, RejectedJobRequest):
            if prepared_job.required_price is not None:
                await self._send_event(
                    build_payment_required_event(
                        event_id,
                        customer_pubkey,
                        prepared_job.required_price,
                    ),
                    require_success=True,
                )
                self._logger.info(
                    "job_payment_required",
                    event_id=event_id,
                    price=prepared_job.required_price,
                    bid=prepared_job.bid,
                )
                return 1, 0, 0, 1
            error_message = prepared_job.error_message
            if error_message is None:
                raise RuntimeError("dvm job rejection missing client error message")
            await self._send_event(
                build_error_event(
                    event_id,
                    customer_pubkey,
                    error_message,
                ),
                require_success=True,
            )
            return 1, 0, 1, 0

        read_model_id = prepared_job.read_model_id
        read_model = prepared_job.read_model

        start = time.monotonic()
        result = await self._read_models.query_entry(self._brotr, read_model, prepared_job.query)
        duration_ms = (time.monotonic() - start) * 1000

        await self._send_event(
            build_result_event(
                ResultEventRequest(
                    request_kind=self._config.kind,
                    request_event_id=event_id,
                    customer_pubkey=customer_pubkey,
                    read_model_id=read_model_id,
                ),
                result,
                prepared_job.price,
            ),
            require_success=True,
        )
        self._logger.info(
            "job_completed",
            event_id=event_id,
            read_model=read_model_id,
            rows=len(result.rows),
            duration_ms=round(duration_ms, 1),
        )
        return 1, 1, 0, 0

    # ── Metrics & dedup ───────────────────────────────────────────

    def _report_metrics(
        self,
        received: int,
        processed: int,
        failed: int,
        payment_required: int,
    ) -> None:
        """Update Prometheus metrics and log cycle stats."""
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

    # ── Read-model policy helpers ─────────────────────────────────

    # ── Event fetching ────────────────────────────────────────────

    async def _restore_request_cursor(self) -> tuple[int, str]:
        """Load the persisted request cursor or initialize it from wall clock."""
        cursor = (
            await self._state_store.fetch_cursors(
                ServiceName.DVM,
                [_REQUEST_CURSOR_KEY],
                DvmRequestCursor,
            )
        )[0]
        if cursor.timestamp > 0:
            self._logger.info(
                "request_cursor_restored",
                timestamp=cursor.timestamp,
                event_id=cursor.id,
            )
            return cursor.timestamp, cursor.id

        timestamp = int(time.time())
        await self._store_request_cursor(timestamp, _REQUEST_CURSOR_DEFAULT_ID)
        self._logger.info(
            "request_cursor_initialized",
            timestamp=timestamp,
            event_id=_REQUEST_CURSOR_DEFAULT_ID,
        )
        return timestamp, _REQUEST_CURSOR_DEFAULT_ID

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

        queue: asyncio.Queue[Any] = asyncio.Queue()
        filter_ = (
            Filter().kind(Kind(self._config.kind)).since(Timestamp.from_secs(self._last_fetch_ts))
        )
        urls = [RelayUrl.parse(url) for url in connected_relays]
        output = await self._client.subscribe_to(urls, filter_)
        successful_relays, failed_relays = normalize_send_output(output)

        for relay_url, error in failed_relays.items():
            self._logger.warning(
                "request_subscription_relay_failed",
                url=relay_url,
                error=error,
            )
        if not successful_relays:
            raise TimeoutError("dvm could not subscribe to any relay")

        self._request_events = queue
        self._request_subscription_id = output.id
        handler = _RequestNotificationBuffer(
            subscription_id=output.id,
            queue=queue,
            logger=self._logger,
        )
        self._notification_task = asyncio.create_task(self._client.handle_notifications(handler))
        self._logger.info(
            "request_subscription_started",
            subscription_id=output.id,
            relays=len(successful_relays),
            since=self._last_fetch_ts,
        )

    async def _stop_request_subscription(self) -> None:
        """Stop the long-lived DVM request subscription notification loop."""
        task = self._notification_task
        self._notification_task = None
        self._request_events = None
        self._request_subscription_id = None
        if task is None:
            return
        if task.done():
            if task.cancelled():
                return
            error = task.exception()
            if error is not None:
                self._logger.warning(
                    "request_subscription_task_failed_on_shutdown",
                    error=str(error),
                    error_type=type(error).__name__,
                )
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _fetch_job_requests(self) -> list[Any]:
        """Drain buffered NIP-90 job request events from the live subscription."""
        if self._client is None or self._request_events is None:
            return []

        events: list[Any] = []
        while True:
            try:
                events.append(self._request_events.get_nowait())
            except asyncio.QueueEmpty:
                break
        events.sort(key=self._event_position)
        return events

    def _event_position(self, event: Any) -> tuple[int, str]:
        """Return the monotonic replay cursor for a request event."""
        return event.created_at().as_secs(), event.id().to_hex()

    # ── Event publishing ──────────────────────────────────────────

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
