"""NIP-90 Data Vending Machine service for Nostr protocol database queries.

Listens for kind 5050 job requests on configured relays, executes
read-only queries via the shared
[Catalog][bigbrotr.services.common.catalog.Catalog], and publishes
results as kind 6050 events.  Per-table pricing via
[DvmTablePolicy][bigbrotr.services.common.catalog.DvmTablePolicy]
enables the NIP-90 bid/payment-required mechanism.

Each ``run()`` cycle polls for new job requests using ``fetch_events()``
with a ``since`` timestamp filter, processes them, and publishes results
or error feedback.

See Also:
    [Catalog][bigbrotr.services.common.catalog.Catalog]: Schema
        introspection and query builder shared with the API service.
    [BaseService][bigbrotr.core.base_service.BaseService]: Abstract
        base class providing lifecycle and metrics.
"""

from __future__ import annotations

import contextlib
import json
import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any, ClassVar

from nostr_sdk import (
    Client,
    EventBuilder,
    Filter,
    Kind,
    RelayUrl,
    Tag,
    Timestamp,
)
from pydantic import Field

from bigbrotr.core.base_service import BaseService, BaseServiceConfig
from bigbrotr.models.constants import ServiceName
from bigbrotr.services.common.catalog import Catalog, DvmTablePolicy, QueryResult
from bigbrotr.utils.keys import KeysConfig
from bigbrotr.utils.protocol import create_client


if TYPE_CHECKING:
    from types import TracebackType

    from bigbrotr.core.brotr import Brotr

# Maximum number of processed event IDs to track before resetting
_MAX_PROCESSED_IDS = 10_000

# Minimum tag lengths for NIP-90 tag parsing
_MIN_PARAM_TAG_LEN = 3
_MIN_TAG_LEN = 2


class DvmConfig(BaseServiceConfig, KeysConfig):
    """Configuration for the DVM service.

    Inherits key management from
    [KeysConfig][bigbrotr.utils.keys.KeysConfig] for Nostr signing.

    Attributes:
        relays: Relay URLs to listen on and publish to.
        kind: NIP-90 request event kind (result = kind + 1000).
        max_page_size: Hard ceiling on query limit.
        tables: Per-table DVM policies (enable/disable, pricing).
        announce: Whether to publish a NIP-89 handler announcement at startup.
        fetch_timeout: Timeout in seconds for relay event fetching.
    """

    relays: list[str] = Field(min_length=1)
    kind: int = Field(default=5050, ge=5000, le=5999)
    max_page_size: int = Field(default=1000, ge=1, le=10000)
    tables: dict[str, DvmTablePolicy] = Field(default_factory=dict)
    announce: bool = Field(default=True)
    fetch_timeout: float = Field(default=30.0, ge=1.0, le=300.0)


class Dvm(BaseService[DvmConfig]):
    """NIP-90 Data Vending Machine for BigBrotr database queries.

    Lifecycle:
        1. ``__aenter__``: discover schema, create Nostr client, connect
           to relays, optionally publish NIP-89 announcement.
        2. ``run()``: fetch new job requests, process each, publish results.
        3. ``__aexit__``: disconnect client.
    """

    SERVICE_NAME: ClassVar[ServiceName] = ServiceName.DVM
    CONFIG_CLASS: ClassVar[type[DvmConfig]] = DvmConfig

    def __init__(self, brotr: Brotr, config: DvmConfig | None = None) -> None:
        super().__init__(brotr, config)
        self._catalog = Catalog()
        self._client: Client | None = None
        self._last_fetch_ts: int = 0
        self._processed_ids: set[str] = set()

    async def __aenter__(self) -> Dvm:
        await super().__aenter__()

        await self._catalog.discover(self._brotr)
        self._logger.info(
            "schema_discovered",
            tables=sum(1 for t in self._catalog.tables.values() if not t.is_view),
            views=sum(1 for t in self._catalog.tables.values() if t.is_view),
        )

        client = await create_client(keys=self._config.keys)
        self._client = client

        pubkey = self._config.keys.public_key().to_hex()
        self._logger.info("client_created", pubkey=pubkey)

        for url in self._config.relays:
            await client.add_relay(RelayUrl.parse(url))
            self._logger.info("relay_connected", url=url)
        await client.connect()

        if self._config.announce:
            await self._publish_announcement()

        self._last_fetch_ts = int(time.time())
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: TracebackType | None,
    ) -> None:
        if self._client is not None:
            with contextlib.suppress(Exception):
                await self._client.shutdown()
            self._client = None
            self._logger.info("client_disconnected")
        await super().__aexit__(_exc_type, _exc_val, _exc_tb)

    async def run(self) -> None:
        """Fetch and process NIP-90 job requests for one cycle."""
        if self._client is None:
            return

        # Capture timestamp before fetching so events arriving during
        # processing are not lost (dedup set handles the overlap)
        fetch_ts = int(time.time())
        events = await self._fetch_job_requests()
        if not events:
            self._last_fetch_ts = fetch_ts
            self._report_metrics(_JobCounters())
            return

        counters = _JobCounters()
        pubkey_hex = self._config.keys.public_key().to_hex()

        for event in events:
            await self._process_event(event, pubkey_hex, counters)

        self._manage_dedup_set()
        self._last_fetch_ts = fetch_ts
        self._report_metrics(counters)

    async def _process_event(
        self,
        event: Any,
        pubkey_hex: str,
        counters: _JobCounters,
    ) -> None:
        """Process a single NIP-90 job request event."""
        event_id = event.id().to_hex()

        if event_id in self._processed_ids:
            return

        # Check p-tag targets us (cache as_vec to avoid repeated FFI calls)
        p_tags: list[str] = []
        for tag in event.tags().to_vec():
            values = tag.as_vec()
            if len(values) >= _MIN_TAG_LEN and values[0] == "p":
                p_tags.append(values[1])
        if p_tags and pubkey_hex not in p_tags:
            return

        self._processed_ids.add(event_id)
        counters.received += 1

        customer_pubkey = event.author().to_hex()
        params = self._parse_job_params(event)
        table = params.get("table", "")

        self._logger.info(
            "job_received",
            event_id=event_id,
            table=table,
            customer=customer_pubkey,
        )

        try:
            await self._handle_job(event_id, customer_pubkey, params, table, counters)
        except (ValueError, OSError, TimeoutError) as e:
            with contextlib.suppress(OSError, TimeoutError):
                await self._publish_error(event_id, customer_pubkey, str(e))
            counters.failed += 1
            self._logger.error("job_failed", event_id=event_id, error=str(e))

    async def _handle_job(
        self,
        event_id: str,
        customer_pubkey: str,
        params: dict[str, Any],
        table: str,
        counters: _JobCounters,
    ) -> None:
        """Handle a validated job request: check access, pricing, execute query."""
        if not table or not self._is_table_enabled(table):
            await self._publish_error(
                event_id,
                customer_pubkey,
                f"Invalid or disabled table: {table}",
            )
            counters.failed += 1
            return

        price = self._get_table_price(table)
        if price > 0:
            bid = params.get("bid", 0)
            if bid < price:
                await self._publish_payment_required(event_id, customer_pubkey, price)
                counters.payment_required += 1
                self._logger.info(
                    "job_payment_required",
                    event_id=event_id,
                    price=price,
                    bid=bid,
                )
                return

        try:
            limit = int(params.get("limit", 100))
            offset = int(params.get("offset", 0))
        except (ValueError, TypeError):
            await self._publish_error(
                event_id,
                customer_pubkey,
                "Invalid limit or offset value",
            )
            counters.failed += 1
            return

        start = time.monotonic()
        result = await self._catalog.query(
            self._brotr,
            table,
            limit=limit,
            offset=offset,
            max_page_size=self._config.max_page_size,
            filters=self._parse_query_filters(params.get("filter", "")),
            sort=params.get("sort") or None,
        )
        duration_ms = (time.monotonic() - start) * 1000

        await self._publish_result(event_id, customer_pubkey, result, price)
        counters.processed += 1
        self._logger.info(
            "job_completed",
            event_id=event_id,
            table=table,
            rows=len(result.rows),
            duration_ms=round(duration_ms, 1),
        )

    def _manage_dedup_set(self) -> None:
        """Clear the processed IDs set when it exceeds the maximum size.

        Replay protection: cleared at ``_MAX_PROCESSED_IDS`` to bound memory.
        The ``since`` timestamp filter on subscription provides a secondary
        deduplication window, limiting replays to the current cycle.
        """
        if len(self._processed_ids) >= _MAX_PROCESSED_IDS:
            self._processed_ids.clear()

    def _report_metrics(self, counters: _JobCounters) -> None:
        """Update Prometheus metrics and log cycle stats."""
        self.set_gauge("jobs_received", counters.received)
        self.inc_counter("jobs_processed", counters.processed)
        self.inc_counter("jobs_failed", counters.failed)
        self.inc_counter("jobs_payment_required", counters.payment_required)
        self.set_gauge(
            "tables_exposed",
            sum(1 for n in self._catalog.tables if self._is_table_enabled(n)),
        )
        self._logger.info(
            "cycle_stats",
            jobs_received=counters.received,
            processed=counters.processed,
            failed=counters.failed,
            payment_required=counters.payment_required,
        )

    # -------------------------------------------------------------------
    # Table policy helpers
    # -------------------------------------------------------------------

    def _is_table_enabled(self, name: str) -> bool:
        if name not in self._catalog.tables:
            return False
        policy = self._config.tables.get(name)
        if policy is None:
            return True
        return policy.enabled

    def _get_table_price(self, name: str) -> int:
        policy = self._config.tables.get(name)
        if policy is None:
            return 0
        return policy.price

    # -------------------------------------------------------------------
    # Event parsing
    # -------------------------------------------------------------------

    @staticmethod
    def _parse_job_params(event: Any) -> dict[str, Any]:
        """Extract NIP-90 parameters from event tags."""
        params: dict[str, Any] = {}
        for tag in event.tags().to_vec():
            values = tag.as_vec()
            if len(values) >= _MIN_PARAM_TAG_LEN and values[0] == "param":
                params[values[1]] = values[2]
            elif len(values) >= _MIN_TAG_LEN and values[0] == "bid":
                with contextlib.suppress(ValueError):
                    params["bid"] = int(values[1])
        return params

    @staticmethod
    def _parse_query_filters(filter_str: str) -> dict[str, str] | None:
        """Parse a filter string like ``"network=clearnet,kind=>:100"``."""
        if not filter_str:
            return None
        filters: dict[str, str] = {}
        for raw_part in filter_str.split(","):
            part = raw_part.strip()
            if "=" not in part:
                continue
            key, _, value = part.partition("=")
            filters[key.strip()] = value.strip()
        return filters or None

    # -------------------------------------------------------------------
    # Event fetching
    # -------------------------------------------------------------------

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

    # -------------------------------------------------------------------
    # Event publishing
    # -------------------------------------------------------------------

    async def _publish_result(
        self,
        request_event_id: str,
        customer_pubkey: str,
        result: QueryResult,
        price: int,
    ) -> None:
        """Publish a kind 6050 result event."""
        if self._client is None:
            return

        result_kind = self._config.kind + 1000
        content = json.dumps(
            {
                "data": result.rows,
                "meta": {
                    "total": result.total,
                    "limit": result.limit,
                    "offset": result.offset,
                },
            },
            default=str,
        )

        tags = [
            Tag.parse(["e", request_event_id]),
            Tag.parse(["p", customer_pubkey]),
            Tag.parse(
                [
                    "request",
                    json.dumps(
                        {
                            "id": request_event_id,
                            "kind": self._config.kind,
                        }
                    ),
                ]
            ),
        ]
        if price > 0:
            tags.append(Tag.parse(["amount", str(price)]))

        builder = EventBuilder(Kind(result_kind), content).tags(tags)
        await self._client.send_event_builder(builder)

    async def _publish_error(
        self,
        request_event_id: str,
        customer_pubkey: str,
        error_message: str,
    ) -> None:
        """Publish a kind 7000 error feedback event."""
        if self._client is None:
            return

        tags = [
            Tag.parse(["status", "error", error_message]),
            Tag.parse(["e", request_event_id]),
            Tag.parse(["p", customer_pubkey]),
        ]
        builder = EventBuilder(Kind(7000), "").tags(tags)
        await self._client.send_event_builder(builder)

    async def _publish_payment_required(
        self,
        request_event_id: str,
        customer_pubkey: str,
        price: int,
    ) -> None:
        """Publish a kind 7000 payment-required feedback event."""
        if self._client is None:
            return

        tags = [
            Tag.parse(["status", "payment-required", f"This query costs {price} millisats"]),
            Tag.parse(["e", request_event_id]),
            Tag.parse(["p", customer_pubkey]),
            Tag.parse(["amount", str(price)]),
        ]
        builder = EventBuilder(Kind(7000), "").tags(tags)
        await self._client.send_event_builder(builder)

    async def _publish_announcement(self) -> None:
        """Publish a NIP-89 handler announcement (kind 31990)."""
        if self._client is None:
            return

        tags = [
            Tag.parse(["d", "bigbrotr-dvm"]),
            Tag.parse(["k", str(self._config.kind)]),
        ]

        tables_info = [
            name for name in sorted(self._catalog.tables) if self._is_table_enabled(name)
        ]
        content = json.dumps(
            {
                "name": "BigBrotr DVM",
                "about": "Read-only access to BigBrotr relay monitoring data",
                "tables": tables_info,
            }
        )

        builder = EventBuilder(Kind(31990), content).tags(tags)
        await self._client.send_event_builder(builder)
        self._logger.info(
            "announcement_published",
            kind=31990,
            relays=len(self._config.relays),
        )


class _JobCounters:
    """Mutable counters for tracking job processing within a single cycle."""

    __slots__ = ("failed", "payment_required", "processed", "received")

    def __init__(self) -> None:
        self.received = 0
        self.processed = 0
        self.failed = 0
        self.payment_required = 0
