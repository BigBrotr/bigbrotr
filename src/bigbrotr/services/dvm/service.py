"""NIP-90 Data Vending Machine service for Nostr protocol database queries.

Listens for NIP-90 job requests on configured relays, executes
read-only queries via the shared
[Catalog][bigbrotr.services.common.catalog.Catalog], and publishes
results as job-result events (request kind + 1000).  Per-table pricing via
[TableConfig][bigbrotr.services.common.configs.TableConfig]
enables the NIP-90 bid/payment-required mechanism.

Each ``run()`` cycle polls for new job requests using ``fetch_events()``
with a ``since`` timestamp filter, processes them, and publishes results
or error feedback.

Note:
    Event IDs are deduplicated in-memory (capped at 10,000) to avoid
    processing the same job twice within the ``since`` overlap window.
    The ``since`` timestamp filter provides a secondary deduplication
    boundary so that the in-memory set only needs to cover the current
    cycle.

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

    brotr = Brotr.from_yaml("config/brotr.yaml")
    dvm = Dvm.from_yaml("config/services/dvm.yaml", brotr=brotr)

    async with brotr:
        async with dvm:
            await dvm.run_forever()
    ```
"""

from __future__ import annotations

import contextlib
import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any, ClassVar

import asyncpg
from nostr_sdk import Client, Filter, Kind, Timestamp

from bigbrotr.core.base_service import BaseService
from bigbrotr.models.constants import ServiceName
from bigbrotr.services.common.catalog import CatalogError
from bigbrotr.services.common.mixins import CatalogAccessMixin
from bigbrotr.services.common.read_models import (
    ReadModelEntry,
    ReadModelQuery,
    enabled_read_models_for_surface,
)
from bigbrotr.services.common.state_store import ServiceStateStore
from bigbrotr.services.common.types import Checkpoint
from bigbrotr.utils.protocol import create_connected_client

from .configs import DvmConfig
from .utils import (
    build_announcement_event,
    build_error_event,
    build_payment_required_event,
    build_result_event,
    parse_job_params,
    parse_query_filters,
)


if TYPE_CHECKING:
    from types import TracebackType

    from nostr_sdk import Keys

    from bigbrotr.core.brotr import Brotr

_MAX_PROCESSED_IDS = 10_000
_MIN_TAG_LEN = 2
_REQUEST_CHECKPOINT_KEY = "job_requests"


class Dvm(CatalogAccessMixin, BaseService[DvmConfig]):
    """NIP-90 Data Vending Machine for BigBrotr database queries.

    Processes NIP-90 job requests (default Kind 5050) by executing
    read-only database queries and publishing results (Kind 6050).
    Supports per-table pricing with bid/payment-required negotiation.

    Lifecycle:
        1. ``__aenter__``: discover schema, create Nostr client, connect
           to relays, optionally publish NIP-89 announcement.
        2. ``run()``: fetch new job requests, process each, publish results.
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
        self._client: Client | None = None
        self._keys: Keys = self._config.keys.keys
        self._last_fetch_ts: int = 0
        self._processed_ids: set[str] = set()

    async def __aenter__(self) -> Dvm:
        await super().__aenter__()
        keys = self._keys

        client, connect_result = await create_connected_client(
            self._config.relays,
            keys=keys,
            timeout=self._config.fetch_timeout,
            allow_insecure=self._config.allow_insecure,
        )
        self._client = client

        pubkey = keys.public_key().to_hex()
        self._logger.info("client_created", pubkey=pubkey)
        for relay_url in connect_result.connected:
            self._logger.info("relay_connected", url=relay_url)
        for relay_url, error in connect_result.failed.items():
            self._logger.warning("relay_connect_failed", url=relay_url, error=error)
        if not connect_result.connected:
            from bigbrotr.utils.protocol import shutdown_client  # noqa: PLC0415

            await shutdown_client(client)
            self._client = None
            raise TimeoutError("dvm could not connect to any relay")

        if self._config.announce:
            await self._publish_announcement()

        self.set_gauge(
            "tables_exposed",
            len(self._enabled_read_model_names()),
        )

        self._last_fetch_ts = await self._restore_fetch_checkpoint()
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
        """No-op: Dvm does not use service state."""
        return 0

    async def run(self) -> None:
        """Fetch and process NIP-90 job requests for one cycle.

        Captures the current timestamp before fetching so that events
        arriving during processing are not lost (the dedup set handles
        the overlap window).  After processing, updates metrics and
        manages the dedup set size.
        """
        if self._client is None:
            return

        # Capture timestamp before fetching so events arriving during
        # processing are not lost (dedup set handles the overlap)
        fetch_ts = int(time.time())
        events = await self._fetch_job_requests()
        if not events:
            await self._store_fetch_checkpoint(fetch_ts)
            self._report_metrics(0, 0, 0, 0)
            return

        received = 0
        processed = 0
        failed = 0
        payment_required = 0
        keys = self._keys
        pubkey_hex = keys.public_key().to_hex()

        for event in events:
            r, p, f, pr = await self._process_event(event, pubkey_hex)
            received += r
            processed += p
            failed += f
            payment_required += pr

        self._manage_dedup_set()
        await self._store_fetch_checkpoint(fetch_ts)
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
        table = params.get("table", "")

        self._logger.info(
            "job_received",
            event_id=event_id,
            table=table,
            customer=customer_pubkey,
        )

        try:
            return await self._handle_job(event_id, customer_pubkey, params, table)
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
        table: str,
    ) -> tuple[int, int, int, int]:
        """Handle a validated job request: check access, pricing, execute query.

        Returns:
            Tuple of (received, processed, failed, payment_required) deltas.
        """
        read_model = self._enabled_read_models().get(table)
        if read_model is None:
            await self._send_event(
                build_error_event(event_id, customer_pubkey, f"Invalid or disabled table: {table}"),
                require_success=True,
            )
            return 1, 0, 1, 0

        price = self._get_table_price(table)
        if price > 0:
            bid = params.get("bid", 0)
            if bid < price:
                await self._send_event(
                    build_payment_required_event(event_id, customer_pubkey, price),
                    require_success=True,
                )
                self._logger.info(
                    "job_payment_required",
                    event_id=event_id,
                    price=price,
                    bid=bid,
                )
                return 1, 0, 0, 1

        try:
            limit = int(params.get("limit", self._config.default_page_size))
            offset = int(params.get("offset", 0))
        except (ValueError, TypeError):
            await self._send_event(
                build_error_event(event_id, customer_pubkey, "Invalid limit or offset value"),
                require_success=True,
            )
            return 1, 0, 1, 0

        start = time.monotonic()
        result = await read_model.query(
            self._brotr,
            self._catalog,
            ReadModelQuery(
                limit=limit,
                offset=offset,
                max_page_size=self._config.max_page_size,
                filters=parse_query_filters(params.get("filter", "")),
                sort=params.get("sort") or None,
            ),
        )
        duration_ms = (time.monotonic() - start) * 1000

        await self._send_event(
            build_result_event(
                self._config.kind,
                event_id,
                customer_pubkey,
                result,
                price,
            ),
            require_success=True,
        )
        self._logger.info(
            "job_completed",
            event_id=event_id,
            table=table,
            rows=len(result.rows),
            duration_ms=round(duration_ms, 1),
        )
        return 1, 1, 0, 0

    # ── Metrics & dedup ───────────────────────────────────────────

    def _manage_dedup_set(self) -> None:
        """Clear the processed IDs set when it exceeds the maximum size.

        Replay protection: cleared at ``_MAX_PROCESSED_IDS`` to bound memory.
        The ``since`` timestamp filter on subscription provides a secondary
        deduplication window, limiting replays to the current cycle.
        """
        if len(self._processed_ids) >= _MAX_PROCESSED_IDS:
            self._processed_ids.clear()

    def _report_metrics(
        self,
        received: int,
        processed: int,
        failed: int,
        payment_required: int,
    ) -> None:
        """Update Prometheus metrics and log cycle stats."""
        self.inc_counter("requests_total", received)
        self.inc_counter("requests_failed", failed)
        self.set_gauge(
            "tables_exposed",
            len(self._enabled_read_model_names()),
        )
        self._logger.info(
            "cycle_stats",
            jobs_received=received,
            processed=processed,
            failed=failed,
            payment_required=payment_required,
        )

    # ── Table policy helpers ──────────────────────────────────────

    def _is_table_enabled(self, name: str) -> bool:
        if name not in self._catalog.tables:
            return False
        return super()._is_table_enabled(name)

    def _get_table_price(self, name: str) -> int:
        policy = self._config.tables.get(name)
        if policy is None:
            return 0
        return policy.price

    def _enabled_read_model_names(self) -> list[str]:
        """Return enabled DVM read models that are present in the discovered catalog."""
        return list(self._enabled_read_models())

    def _enabled_read_models(self) -> dict[str, ReadModelEntry]:
        """Return enabled DVM read models keyed by public read-model ID."""
        enabled_names = {name for name in self._config.tables if self._is_table_enabled(name)}
        return {
            read_model_id: entry
            for read_model_id, entry in enabled_read_models_for_surface(
                "dvm",
                available_catalog_names=set(self._catalog.tables),
                enabled_names=enabled_names,
            ).items()
            if entry.catalog_name in self._catalog.tables and self._is_table_enabled(read_model_id)
        }

    # ── Event fetching ────────────────────────────────────────────

    async def _restore_fetch_checkpoint(self) -> int:
        """Load the persisted request boundary or initialize it from wall clock."""
        checkpoint = (
            await ServiceStateStore(self._brotr).fetch_checkpoints(
                ServiceName.DVM,
                [_REQUEST_CHECKPOINT_KEY],
                Checkpoint,
            )
        )[0]
        if checkpoint.timestamp > 0:
            self._logger.info("request_checkpoint_restored", timestamp=checkpoint.timestamp)
            return checkpoint.timestamp

        timestamp = int(time.time())
        await self._store_fetch_checkpoint(timestamp)
        self._logger.info("request_checkpoint_initialized", timestamp=timestamp)
        return timestamp

    async def _store_fetch_checkpoint(self, timestamp: int) -> None:
        """Persist the current request boundary after a successful cycle."""
        self._last_fetch_ts = timestamp
        await ServiceStateStore(self._brotr).upsert_checkpoints(
            ServiceName.DVM,
            [Checkpoint(key=_REQUEST_CHECKPOINT_KEY, timestamp=timestamp)],
        )

    async def _fetch_job_requests(self) -> list[Any]:
        """Fetch new NIP-90 job request events since last timestamp."""
        if self._client is None:
            return []

        f = Filter().kind(Kind(self._config.kind)).since(Timestamp.from_secs(self._last_fetch_ts))
        events_obj = await self._client.fetch_events(
            f,
            timedelta(seconds=self._config.fetch_timeout),
        )
        return list(events_obj.to_vec())

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
        successful_relays = tuple(str(relay_url) for relay_url in output.success)
        failed_relays = {str(relay_url): str(error) for relay_url, error in output.failed.items()}

        if require_success and not successful_relays:
            raise OSError("event was not accepted by any relay")

        return successful_relays, failed_relays

    async def _publish_announcement(self) -> None:
        """Publish a NIP-89 handler announcement (kind 31990)."""
        if self._client is None:
            return

        tables_info = self._enabled_read_model_names()
        builder = build_announcement_event(
            d_tag=self._config.d_tag,
            kind=self._config.kind,
            name=self._config.name,
            about=self._config.about,
            tables=tables_info,
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
