"""
Monitor Service for BigBrotr.

Monitors relay health and metadata with full NIP-66 compliance:
- Check relay connectivity (open, read, write tests)
- Fetch NIP-11 relay information document
- Perform DNS resolution timing
- Validate SSL/TLS certificates
- Geolocate relay IP addresses
- Publish Kind 30166 relay discovery events
- Publish Kind 10166 monitor announcements

Usage:
    from core import Brotr
    from services import Monitor

    brotr = Brotr.from_yaml("yaml/core/brotr.yaml")
    monitor = Monitor.from_yaml("yaml/services/monitor.yaml", brotr=brotr)

    async with brotr.pool:
        async with monitor:
            await monitor.run_forever(interval=3600)
"""

from __future__ import annotations

import asyncio
import time
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Optional

import geoip2.database
from nostr_sdk import (
    ClientBuilder,
    ClientOptions,
    EventBuilder,
    Kind,
    Tag,
)
from pydantic import BaseModel, Field, model_validator

from core.base_service import BaseService
from models import (
    Keys as ModelKeys,
)
from models import (
    Nip11,
    Nip66,
    Relay,
    RelayMetadata,
)


if TYPE_CHECKING:
    from core.brotr import Brotr


# =============================================================================
# Configuration
# =============================================================================


class TorConfig(BaseModel):
    """Tor proxy configuration for .onion relay support."""

    enabled: bool = Field(default=True, description="Enable Tor proxy for .onion relays")
    host: str = Field(default="127.0.0.1", description="Tor proxy host")
    port: int = Field(default=9050, ge=1, le=65535, description="Tor proxy port")

    @property
    def proxy_url(self) -> str:
        """Get the SOCKS5 proxy URL for aiohttp-socks."""
        return f"socks5://{self.host}:{self.port}"


class KeysConfig(BaseModel):
    """Nostr keys configuration for NIP-66 publishing."""

    model_config = {"arbitrary_types_allowed": True}

    keys: Optional[ModelKeys] = Field(
        default=None,
        description="Keys loaded from PRIVATE_KEY env",
    )

    @model_validator(mode="before")
    @classmethod
    def load_keys_from_env(cls, data: Any) -> Any:
        if isinstance(data, dict) and "keys" not in data:
            data["keys"] = ModelKeys.from_env()
        return data


class PublishingConfig(BaseModel):
    """Publishing configuration for NIP-66 events."""

    enabled: bool = Field(default=True, description="Enable NIP-66 event publishing")
    destination: str = Field(
        default="monitored_relay",
        description="Where to publish: 'monitored_relay', 'configured_relays', 'database_only'",
    )
    relays: list[str] = Field(
        default_factory=list,
        description="Relay URLs for publishing (only used if destination='configured_relays')",
    )


class ChecksConfig(BaseModel):
    """Configuration for which checks to perform."""

    open: bool = Field(default=True, description="Test WebSocket connection")
    read: bool = Field(default=True, description="Test REQ/EOSE subscription")
    write: bool = Field(default=True, description="Test EVENT/OK publication")
    nip11: bool = Field(default=True, description="Fetch NIP-11 info document")
    ssl: bool = Field(default=True, description="Validate SSL/TLS certificate")
    dns: bool = Field(default=True, description="Measure DNS resolution time")
    geo: bool = Field(default=True, description="Geolocate relay IP address")


class GeoConfig(BaseModel):
    """Geolocation configuration."""

    database_path: str = Field(
        default="/usr/share/GeoIP/GeoLite2-City.mmdb",
        description="Path to MaxMind GeoLite2-City database",
    )
    asn_database_path: Optional[str] = Field(
        default=None,
        description="Path to MaxMind GeoLite2-ASN database (optional)",
    )


class TimeoutsConfig(BaseModel):
    """Timeout configuration for relay checks."""

    clearnet: float = Field(
        default=30.0, ge=5.0, le=120.0, description="Timeout for clearnet relay checks in seconds"
    )
    tor: float = Field(
        default=60.0, ge=10.0, le=180.0, description="Timeout for Tor relay checks in seconds"
    )


class ConcurrencyConfig(BaseModel):
    """Concurrency configuration for parallel relay checking."""

    max_parallel: int = Field(
        default=50, ge=1, le=500, description="Maximum concurrent relay checks per process"
    )
    max_processes: int = Field(default=1, ge=1, le=32, description="Number of worker processes")
    batch_size: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Number of relays to process before pushing to database",
    )


class SelectionConfig(BaseModel):
    """Configuration for relay selection."""

    min_age_since_check: int = Field(
        default=3600,  # 1 hour
        ge=0,
        description="Minimum seconds since last check",
    )


class MonitorConfig(BaseModel):
    """Monitor configuration."""

    interval: float = Field(default=3600.0, ge=60.0, description="Seconds between monitor cycles")
    tor: TorConfig = Field(default_factory=TorConfig)
    keys: KeysConfig = Field(default_factory=KeysConfig)
    publishing: PublishingConfig = Field(default_factory=PublishingConfig)
    checks: ChecksConfig = Field(default_factory=ChecksConfig)
    geo: GeoConfig = Field(default_factory=GeoConfig)
    timeouts: TimeoutsConfig = Field(default_factory=TimeoutsConfig)
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    selection: SelectionConfig = Field(default_factory=SelectionConfig)

    @model_validator(mode="after")
    def validate_publishing_requires_key(self) -> MonitorConfig:
        """Fail-fast: If publishing enabled, private key MUST be configured."""
        if self.publishing.enabled and self.publishing.destination != "database_only":
            if not self.keys.keys:
                raise ValueError(
                    "publishing.enabled=true requires PRIVATE_KEY environment variable. "
                    "Set publishing.destination='database_only' to disable event publishing."
                )
        return self

    @model_validator(mode="after")
    def validate_geo_database_exists(self) -> MonitorConfig:
        """Fail-fast: If geo check enabled, database MUST exist."""
        if self.checks.geo:
            path = Path(self.geo.database_path)
            if not path.exists():
                raise ValueError(
                    f"geo.database_path does not exist: {self.geo.database_path}. "
                    "Download MaxMind GeoLite2-City database or set checks.geo=false."
                )
        return self


# =============================================================================
# Helpers
# =============================================================================


async def fetch_nip11(relay: Relay, timeout: float, tor_config: TorConfig) -> Optional[Nip11]:
    """Fetch NIP-11 relay information document via HTTP."""
    is_tor = relay.network == "tor"
    proxy_url = tor_config.proxy_url if is_tor and tor_config.enabled else None
    return await Nip11.fetch(relay, timeout=timeout, proxy_url=proxy_url)


def _determine_relay_type(limitation: dict[str, Any]) -> Optional[str]:
    """
    Determine relay type based on NIP-11 limitation fields.

    Returns one of: "Paid", "Private", "AuthRequired", "RestrictedWrite", "Public", or None.
    """
    auth_required = limitation.get("auth_required", False)
    payment_required = limitation.get("payment_required", False)
    restricted_writes = limitation.get("restricted_writes", False)

    if payment_required:
        return "Paid"
    elif auth_required and restricted_writes:
        return "Private"
    elif auth_required:
        return "AuthRequired"
    elif restricted_writes:
        return "RestrictedWrite"
    else:
        return "Public"


def _extract_kinds_from_retention(retention: list[dict[str, Any]]) -> list[str]:
    """
    Extract kind information from NIP-11 retention field.

    Returns list of kind strings with optional ! prefix for excluded kinds.
    """
    kinds: list[str] = []

    for entry in retention:
        # Entry can have "kinds" array or "kind" single value
        entry_kinds = entry.get("kinds", [])
        if "kind" in entry:
            entry_kinds = [entry["kind"]]

        # Check if this is a discard rule (time=0 or count=0)
        is_discard = entry.get("time") == 0 or entry.get("count") == 0

        for kind in entry_kinds:
            kind_str = str(kind)
            if is_discard:
                kinds.append(f"!{kind_str}")
            else:
                kinds.append(kind_str)

    return kinds


def build_kind_30166_tags(
    relay: Relay, nip11: Optional[Nip11], nip66: Optional[Nip66]
) -> list[Tag]:
    """Build NIP-66 Kind 30166 event tags."""
    tags = [
        Tag.parse(["d", relay.url]),
        Tag.parse(["n", relay.network]),
    ]

    if nip66:
        if nip66.rtt_open is not None:
            tags.append(Tag.parse(["rtt-open", str(nip66.rtt_open)]))
        if nip66.rtt_read is not None:
            tags.append(Tag.parse(["rtt-read", str(nip66.rtt_read)]))
        if nip66.rtt_write is not None:
            tags.append(Tag.parse(["rtt-write", str(nip66.rtt_write)]))
        if nip66.geohash:
            tags.append(Tag.parse(["g", nip66.geohash]))

    if nip11:
        # Add supported NIPs
        if nip11.supported_nips:
            for nip in nip11.supported_nips:
                tags.append(Tag.parse(["N", str(nip)]))

        # Add requirements from limitation
        if nip11.limitation:
            lim = nip11.limitation
            if lim.get("auth_required"):
                tags.append(Tag.parse(["R", "auth"]))
            else:
                tags.append(Tag.parse(["R", "!auth"]))

            if lim.get("payment_required"):
                tags.append(Tag.parse(["R", "payment"]))
            else:
                tags.append(Tag.parse(["R", "!payment"]))

            if lim.get("restricted_writes"):
                tags.append(Tag.parse(["R", "writes"]))
            else:
                tags.append(Tag.parse(["R", "!writes"]))

            min_pow = lim.get("min_pow_difficulty", 0)
            if min_pow and min_pow > 0:
                tags.append(Tag.parse(["R", "pow"]))
            else:
                tags.append(Tag.parse(["R", "!pow"]))

            # T tag: Relay type
            relay_type = _determine_relay_type(lim)
            if relay_type:
                tags.append(Tag.parse(["T", relay_type]))

        # k tag: Accepted/unaccepted kinds from retention
        if nip11.retention:
            kinds = _extract_kinds_from_retention(nip11.retention)
            for kind in kinds:
                tags.append(Tag.parse(["k", kind]))

        # t tag: Topics from relay tags
        if nip11.tags:
            for topic in nip11.tags:
                tags.append(Tag.parse(["t", topic]))

    return tags


def build_kind_10166_tags(config: MonitorConfig) -> list[Tag]:
    """Build NIP-66 Kind 10166 monitor announcement tags."""
    tags = [
        Tag.parse(["frequency", str(int(config.interval))]),
        Tag.parse(["timeout", "open", str(int(config.timeouts.clearnet * 1000))]),
        Tag.parse(["timeout", "read", str(int(config.timeouts.clearnet * 1000))]),
        Tag.parse(["timeout", "write", str(int(config.timeouts.clearnet * 1000))]),
    ]

    # Add checks being performed
    if config.checks.open:
        tags.append(Tag.parse(["c", "open"]))
    if config.checks.read:
        tags.append(Tag.parse(["c", "read"]))
    if config.checks.write:
        tags.append(Tag.parse(["c", "write"]))
    if config.checks.nip11:
        tags.append(Tag.parse(["c", "nip11"]))
    if config.checks.ssl:
        tags.append(Tag.parse(["c", "ssl"]))
    if config.checks.dns:
        tags.append(Tag.parse(["c", "dns"]))
    if config.checks.geo:
        tags.append(Tag.parse(["c", "geo"]))

    return tags


# =============================================================================
# Service
# =============================================================================


class Monitor(BaseService[MonitorConfig]):
    """
    Relay health monitoring service with full NIP-66 compliance.

    Checks relay connectivity and capabilities:
    - NIP-11: Fetches relay info document
    - NIP-66: Tests read/write capabilities and measures RTT
    - DNS: Measures resolution time
    - SSL: Validates certificate
    - Geo: Geolocates relay IP

    Results are stored in relay_metadata table and optionally
    published as Kind 30166 events.
    """

    SERVICE_NAME: ClassVar[str] = "monitor"
    CONFIG_CLASS: ClassVar[type[MonitorConfig]] = MonitorConfig

    def __init__(
        self,
        brotr: Brotr,
        config: Optional[MonitorConfig] = None,
    ) -> None:
        super().__init__(brotr=brotr, config=config)
        self._config: MonitorConfig

        # Keys for signing events and NIP-66 tests (models.Keys extends nostr_sdk.Keys)
        self._keys: Optional[ModelKeys] = self._config.keys.keys

        # GeoIP reader (lazy loaded)
        self._geo_reader: Optional[geoip2.database.Reader] = None
        self._asn_reader: Optional[geoip2.database.Reader] = None

        # Metrics (protected by lock to prevent race conditions)
        self._metrics_lock: asyncio.Lock = asyncio.Lock()
        self._checked_relays: int = 0
        self._successful_checks: int = 0
        self._failed_checks: int = 0
        self._last_announcement: float = 0

    async def __aenter__(self) -> Monitor:
        """Initialize resources on context entry."""
        await super().__aenter__()

        # Open GeoIP database readers
        if self._config.checks.geo:
            self._geo_reader = geoip2.database.Reader(self._config.geo.database_path)
            if self._config.geo.asn_database_path:
                self._asn_reader = geoip2.database.Reader(self._config.geo.asn_database_path)

        return self

    async def __aexit__(self, *args: Any) -> None:
        """Cleanup resources on context exit."""
        # Close GeoIP readers
        if self._geo_reader:
            self._geo_reader.close()
            self._geo_reader = None
        if self._asn_reader:
            self._asn_reader.close()
            self._asn_reader = None

        await super().__aexit__(*args)

    async def run(self) -> None:
        """Run single monitoring cycle."""
        cycle_start = time.time()
        self._checked_relays = 0
        self._successful_checks = 0
        self._failed_checks = 0

        # Publish Kind 10166 announcement if publishing enabled (once per hour max)
        if (
            self._config.publishing.enabled
            and self._config.publishing.destination != "database_only"
        ):
            if time.time() - self._last_announcement > 3600:
                await self._publish_announcement()
                self._last_announcement = time.time()

        # Fetch relays to check
        relays = await self._fetch_relays_to_check()
        if not relays:
            self._logger.info("no_relays_to_check")
            return

        self._logger.info("monitor_started", relay_count=len(relays))

        # Prepare for parallel execution
        semaphore = asyncio.Semaphore(self._config.concurrency.max_parallel)
        metadata_batch: list[RelayMetadata] = []
        successful_relay_urls: list[str] = []  # Track only successfully checked relays

        # Process relays in chunks to limit memory from pending tasks (H11)
        # Chunk size is 4x max_parallel to keep pipeline full without scheduling all at once
        chunk_size = max(self._config.concurrency.max_parallel * 4, 100)

        for chunk_start in range(0, len(relays), chunk_size):
            chunk = relays[chunk_start : chunk_start + chunk_size]

            # Create task-to-relay mapping for this chunk only
            tasks: list[asyncio.Task[list[RelayMetadata] | None]] = []
            task_relays: list[Relay] = []
            for relay in chunk:
                task = asyncio.create_task(self._process_relay(relay, semaphore))
                tasks.append(task)
                task_relays.append(relay)

            # Await all tasks in this chunk
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for relay, result in zip(task_relays, results):
                if isinstance(result, BaseException):
                    self._logger.error(
                        "monitor_task_failed",
                        error=str(result),
                        error_type=type(result).__name__,
                        url=relay.url,
                    )
                    continue
                if result is not None:
                    metadata_batch.extend(result)
                    successful_relay_urls.append(relay.url)

                    # Insert batch if full
                    if len(metadata_batch) >= self._config.concurrency.batch_size:
                        await self._insert_metadata_batch(metadata_batch)
                        metadata_batch = []

        # Insert remaining records
        if metadata_batch:
            await self._insert_metadata_batch(metadata_batch)

        # Save checkpoints only for successfully checked relays
        now = int(time.time())
        checkpoint_data = [
            ("monitor", "checkpoint", url, {"last_check_at": now}) for url in successful_relay_urls
        ]
        if checkpoint_data:
            await self._brotr.upsert_service_data(checkpoint_data)

        # Log stats
        elapsed = time.time() - cycle_start
        self._logger.info(
            "cycle_completed",
            checked=self._checked_relays,
            successful=self._successful_checks,
            failed=self._failed_checks,
            duration=round(elapsed, 2),
        )

    async def _fetch_relays_to_check(self) -> list[Relay]:
        """Fetch relays that need health checking from database using SQL JOIN."""
        relays: list[Relay] = []
        threshold = int(time.time()) - self._config.selection.min_age_since_check

        # Single query with LEFT JOIN to filter relays that need checking
        # This avoids loading all checkpoints and relays into Python memory
        query = """
            SELECT r.url, r.network, r.discovered_at
            FROM relays r
            LEFT JOIN service_data sd ON
                sd.service_name = 'monitor'
                AND sd.data_type = 'checkpoint'
                AND sd.data_key = r.url
            WHERE
                sd.data_key IS NULL
                OR (sd.data->>'last_check_at')::BIGINT < $1
            ORDER BY r.discovered_at ASC
        """
        rows = await self._brotr.pool.fetch(query, threshold)

        skipped_tor = 0

        for row in rows:
            url_str = row["url"]

            try:
                relay = Relay(url_str, discovered_at=row["discovered_at"])
                # Filter Tor relays if proxy disabled
                if relay.network == "tor" and not self._config.tor.enabled:
                    skipped_tor += 1
                    continue
                relays.append(relay)
            except Exception:
                self._logger.debug("invalid_relay_url", url=url_str)

        if skipped_tor > 0:
            self._logger.debug("skipped_tor_relays", count=skipped_tor)

        self._logger.debug("relays_to_check", count=len(relays))
        return relays

    async def _process_relay(
        self, relay: Relay, semaphore: asyncio.Semaphore
    ) -> list[RelayMetadata]:
        """Check a single relay with concurrency limit."""
        async with semaphore:
            # Race condition fix: Protect counter increment with lock
            async with self._metrics_lock:
                self._checked_relays += 1

            is_tor = relay.network == "tor"
            timeout = self._config.timeouts.tor if is_tor else self._config.timeouts.clearnet

            nip11: Optional[Nip11] = None
            nip66: Optional[Nip66] = None
            metadata_records: list[RelayMetadata] = []

            try:
                # NIP-11 check
                if self._config.checks.nip11:
                    nip11 = await fetch_nip11(relay, timeout, self._config.tor)
                    if nip11:
                        metadata_records.append(nip11.to_relay_metadata())

                # NIP-66 test (DNS, SSL, Geo, Connection)
                # Get paths for geo databases if geo check enabled
                city_db_path = None
                asn_db_path = None
                if self._config.checks.geo:
                    city_db_path = self._config.geo.database_path
                    asn_db_path = self._config.geo.asn_database_path

                # Get keys for write test if enabled
                keys = self._keys if self._config.checks.write else None

                # Run all NIP-66 tests via Nip66.test()
                nip66 = await Nip66.test(
                    relay=relay,
                    timeout=timeout,
                    keys=keys,
                    city_db_path=city_db_path,
                    asn_db_path=asn_db_path,
                )

                # Add nip66 metadata records (rtt and optionally geo)
                metadata_records.extend(nip66.to_relay_metadata())

                # Publish Kind 30166 event if enabled
                if (
                    self._config.publishing.enabled
                    and self._config.publishing.destination != "database_only"
                    and self._keys
                ):
                    await self._publish_relay_discovery(relay, nip11, nip66)

                # Race condition fix: Protect counter increments with lock
                if nip66.is_openable or nip11:
                    async with self._metrics_lock:
                        self._successful_checks += 1
                    self._logger.info("check_ok", relay=relay.url)
                else:
                    async with self._metrics_lock:
                        self._failed_checks += 1
                    self._logger.info("check_failed", relay=relay.url)

                return metadata_records

            except Exception as e:
                # Race condition fix: Protect counter increment with lock
                async with self._metrics_lock:
                    self._failed_checks += 1
                self._logger.debug("relay_check_failed", relay=relay.url, error=str(e))
                return []

    async def _insert_metadata_batch(self, batch: list[RelayMetadata]) -> None:
        """Insert a batch of metadata records into database."""
        if not batch:
            return

        try:
            count = await self._brotr.insert_relay_metadata(batch)
            self._logger.debug("metadata_batch_inserted", count=count)
        except Exception as e:
            self._logger.error(
                "metadata_batch_insert_failed",
                error=str(e),
                error_type=type(e).__name__,
                count=len(batch),
            )

    async def _publish_relay_discovery(
        self, relay: Relay, nip11: Optional[Nip11], nip66: Optional[Nip66]
    ) -> None:
        """Publish Kind 30166 relay discovery event."""
        if not self._keys:
            return

        try:
            # Build event content (NIP-11 JSON if available)
            content = ""
            if nip11:
                content = nip11.metadata.data_jsonb

            # Build tags
            tags = build_kind_30166_tags(relay, nip11, nip66)

            # Create and sign event
            builder = EventBuilder.new(Kind(30166), content).tags(tags)

            # Determine destination
            if self._config.publishing.destination == "monitored_relay":
                # Publish to the relay being monitored
                # Resource leak fix: Use try/finally to ensure client shutdown
                opts = ClientOptions().connection_timeout(timedelta(seconds=10))
                client = ClientBuilder().signer(self._keys).opts(opts).build()
                try:
                    await client.add_relay(relay.url)
                    await client.connect()
                    await client.send_event_builder(builder)
                finally:
                    await client.shutdown()

            elif self._config.publishing.destination == "configured_relays":
                # Publish to configured relay list
                # Resource leak fix: Use try/finally to ensure client shutdown
                opts = ClientOptions().connection_timeout(timedelta(seconds=10))
                client = ClientBuilder().signer(self._keys).opts(opts).build()
                try:
                    for url in self._config.publishing.relays:
                        try:
                            await client.add_relay(url)
                        except Exception as e:
                            self._logger.debug("add_relay_failed", url=url, error=str(e))
                    await client.connect()
                    await client.send_event_builder(builder)
                finally:
                    await client.shutdown()

        except Exception as e:
            self._logger.debug("publish_30166_failed", relay=relay.url, error=str(e))

    async def _publish_announcement(self) -> None:
        """Publish Kind 10166 monitor announcement event."""
        if not self._keys:
            return

        try:
            # Build tags
            tags = build_kind_10166_tags(self._config)

            # Create and sign event
            builder = EventBuilder.new(Kind(10166), "").tags(tags)

            # Publish to configured relays
            if self._config.publishing.relays:
                # Resource leak fix: Use try/finally to ensure client shutdown
                opts = ClientOptions().connection_timeout(timedelta(seconds=10))
                client = ClientBuilder().signer(self._keys).opts(opts).build()
                try:
                    for url in self._config.publishing.relays:
                        try:
                            await client.add_relay(url)
                        except Exception as e:
                            self._logger.debug("add_relay_failed", url=url, error=str(e))
                    await client.connect()
                    await client.send_event_builder(builder)
                    self._logger.info("announcement_published")
                finally:
                    await client.shutdown()

        except Exception as e:
            self._logger.warning("publish_10166_failed", error=str(e), error_type=type(e).__name__)
