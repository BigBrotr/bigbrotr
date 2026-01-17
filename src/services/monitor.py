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
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import geoip2.database
from nostr_sdk import (
    EventBuilder,
    Keys,
    Kind,
    Tag,
)
from pydantic import BaseModel, Field, model_validator

from core.base_service import BaseService, BaseServiceConfig
from models import Nip11, Nip66, Relay, RelayMetadata
from models.relay import NetworkType
from utils.keys import KeysConfig
from utils.network import NetworkConfig


if TYPE_CHECKING:
    from core.brotr import Brotr
    from models.nip11 import Nip11Limitation, Nip11RetentionEntry


# =============================================================================
# Constants
# =============================================================================

# Time interval for publishing announcements
ANNOUNCE_INTERVAL = 3600  # 1 hour

# Chunk sizing for multiprocess distribution
CHUNK_MIN_SIZE = 100
CHUNK_MULTIPLIER = 4

# Timeout for publishing events
TIMEOUT_PUBLISH = 10.0


# =============================================================================
# Configuration
# =============================================================================


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
    nip11_max_size: int = Field(
        default=1_048_576,
        ge=1024,
        le=10_485_760,
        description="Maximum NIP-11 response size in bytes (1MB default)",
    )
    ssl: bool = Field(default=True, description="Validate SSL/TLS certificate")
    dns: bool = Field(default=True, description="Measure DNS resolution time")
    geo: bool = Field(default=True, description="Geolocate relay IP address")


class GeoConfig(BaseModel):
    """Geolocation configuration."""

    city_database_path: str = Field(
        default="static/GeoLite2-City.mmdb",
        description="Path to MaxMind GeoLite2-City database",
    )
    asn_database_path: str | None = Field(
        default=None,
        description="Path to MaxMind GeoLite2-ASN database (optional)",
    )
    country_database_path: str | None = Field(
        default=None,
        description="Path to MaxMind GeoLite2-Country database (optional fallback)",
    )
    update_frequency: str = Field(
        default="monthly",
        description="GeoIP update frequency: 'monthly', 'weekly', or 'none'",
    )


class ConcurrencyConfig(BaseModel):
    """Concurrency configuration for parallel relay checking."""

    max_processes: int = Field(default=1, ge=1, le=32, description="Number of worker processes")
    max_parallel: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Maximum parallel relay checks per process",
    )
    batch_size: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Number of relays to process before pushing to database",
    )


class SelectionConfig(BaseModel):
    """Configuration for relay selection."""

    min_age_since_check: int = Field(
        default=3600, ge=0, description="Minimum seconds since last check"
    )


class MonitorConfig(BaseServiceConfig):
    """Monitor configuration."""

    networks: NetworkConfig = Field(default_factory=NetworkConfig)
    keys: KeysConfig = Field(default_factory=lambda: KeysConfig.model_validate({}))
    publishing: PublishingConfig = Field(default_factory=PublishingConfig)
    checks: ChecksConfig = Field(default_factory=ChecksConfig)
    geo: GeoConfig = Field(default_factory=GeoConfig)
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    selection: SelectionConfig = Field(default_factory=SelectionConfig)

    @model_validator(mode="after")
    def validate_geo_database_exists(self) -> MonitorConfig:
        """Fail-fast: If geo check enabled, database MUST exist."""
        if self.checks.geo:
            path = Path(self.geo.city_database_path)
            if not path.exists():
                raise ValueError(
                    f"geo.city_database_path does not exist: {self.geo.city_database_path}. "
                    "Download MaxMind GeoLite2-City database or set checks.geo=false."
                )
        return self


# =============================================================================
# Helpers
# =============================================================================


async def fetch_nip11(
    relay: Relay, timeout: float, max_size: int, network_config: NetworkConfig
) -> Nip11 | None:
    """Fetch NIP-11 relay information document via HTTP.

    Args:
        relay: Relay to fetch NIP-11 from
        timeout: Request timeout in seconds
        max_size: Maximum response size in bytes
        network_config: Network configuration for overlay networks (Tor, I2P, Loki)

    Returns:
        Nip11 instance if successful, None otherwise
    """
    proxy_url = network_config.get_proxy_url(relay.network)
    return await Nip11.fetch(relay, timeout=timeout, max_size=max_size, proxy_url=proxy_url)


def _determine_relay_type(limitation: Nip11Limitation | dict[str, Any]) -> str | None:
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


def _extract_kinds_from_retention(
    retention: list[Nip11RetentionEntry] | list[dict[str, Any]],
) -> list[str]:
    """
    Extract kind information from NIP-11 retention field.

    Returns list of kind strings with optional ! prefix for excluded kinds.
    """
    kinds: list[str] = []

    for entry in retention:
        # Entry has "kinds" array (NIP-11 spec uses "kinds" not "kind")
        entry_kinds: list[int | list[int]] = entry.get("kinds") or []

        # Check if this is a discard rule (time=0 or count=0)
        is_discard = entry.get("time") == 0 or entry.get("count") == 0

        for kind in entry_kinds:
            kind_str = str(kind)
            if is_discard:
                kinds.append(f"!{kind_str}")
            else:
                kinds.append(kind_str)

    return kinds


def build_kind_30166_tags(relay: Relay, nip11: Nip11 | None, nip66: Nip66 | None) -> list[Tag]:
    """Build NIP-66 Kind 30166 relay discovery event tags.

    Constructs a list of tags for a Kind 30166 parametrized replaceable event
    as specified in NIP-66. These tags describe relay metadata, capabilities,
    and health metrics for relay discovery purposes.

    Tag structure per NIP-66:
        - "d": Relay URL (required, makes event parametrized replaceable)
        - "n": Network type (clearnet, tor, i2p, loki)
        - "rtt-open": Round-trip time for WebSocket open in milliseconds
        - "rtt-read": Round-trip time for REQ/EOSE cycle in milliseconds
        - "rtt-write": Round-trip time for EVENT/OK cycle in milliseconds
        - "g": Geohash of relay location (variable precision)
        - "N": Supported NIP numbers (one tag per NIP)
        - "R": Requirements (auth, !auth, payment, !payment, writes, !writes, pow, !pow)
        - "T": Relay type classification (Public, Paid, Private, AuthRequired, RestrictedWrite)
        - "k": Accepted/rejected kinds from retention policy (! prefix means rejected)
        - "t": Topic tags from NIP-11 relay tags field

    Args:
        relay: The relay being described.
        nip11: Optional NIP-11 relay information document with capabilities and policies.
        nip66: Optional NIP-66 health check results with RTT measurements and geolocation.

    Returns:
        List of nostr_sdk Tag objects ready for event construction.

    Example:
        >>> tags = build_kind_30166_tags(relay, nip11, nip66)
        >>> # Results in tags like:
        >>> # [["d", "wss://relay.example.com"], ["n", "clearnet"],
        >>> #  ["rtt-open", "150"], ["N", "1"], ["R", "!auth"], ["T", "Public"]]
    """
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
    """Build NIP-66 Kind 10166 monitor announcement event tags.

    Constructs tags for a Kind 10166 replaceable event that announces this
    monitor's presence and capabilities to the Nostr network. Other clients
    can discover monitors and understand their testing methodology.

    The announcement allows relay operators and users to:
        - Discover active relay monitors on the network
        - Understand what checks each monitor performs
        - Know the frequency and timeout settings used
        - Filter monitoring data by monitor capabilities

    Tag structure per NIP-66:
        - "frequency": How often monitoring runs (in seconds)
        - "timeout": Test timeout values, format ["timeout", <test_type>, <ms>]
            - test_type: "open", "read", "write", "nip11"
            - ms: Timeout in milliseconds
        - "c": Check types performed (one tag per check type)
            - Values: "open", "read", "write", "nip11", "ssl", "dns", "geo"

    Args:
        config: Monitor configuration containing network timeouts, check settings,
            and monitoring interval.

    Returns:
        List of nostr_sdk Tag objects for the Kind 10166 announcement event.

    Example:
        >>> tags = build_kind_10166_tags(config)
        >>> # Results in tags like:
        >>> # [["frequency", "3600"], ["timeout", "open", "10000"],
        >>> #  ["timeout", "read", "10000"], ["c", "open"], ["c", "nip11"]]
    """
    clearnet_timeout_ms = int(config.networks.clearnet.timeout * 1000)
    tags = [
        Tag.parse(["frequency", str(int(config.interval))]),
        Tag.parse(["timeout", "open", str(clearnet_timeout_ms)]),
        Tag.parse(["timeout", "read", str(clearnet_timeout_ms)]),
        Tag.parse(["timeout", "write", str(clearnet_timeout_ms)]),
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
        config: MonitorConfig | None = None,
    ) -> None:
        super().__init__(brotr=brotr, config=config)
        self._config: MonitorConfig

        # Keys for signing events and NIP-66 tests
        self._keys: Keys = self._config.keys.keys

        # GeoIP reader (lazy loaded)
        self._geo_reader: geoip2.database.Reader | None = None
        self._asn_reader: geoip2.database.Reader | None = None

        # Metrics (protected by lock to prevent race conditions)
        self._metrics_lock: asyncio.Lock = asyncio.Lock()
        self._checked_relays: int = 0
        self._successful_checks: int = 0
        self._failed_checks: int = 0
        self._last_announcement: float = 0

    def _open_geo_readers(self) -> None:
        """Open GeoIP database readers for the current run.

        Readers are opened at the start of each run() cycle to allow
        database files to be updated between runs without restarting.
        """
        if not self._config.checks.geo:
            return

        self._geo_reader = geoip2.database.Reader(self._config.geo.city_database_path)
        if self._config.geo.asn_database_path:
            asn_path = Path(self._config.geo.asn_database_path)
            if asn_path.exists():
                self._asn_reader = geoip2.database.Reader(str(asn_path))

    def _close_geo_readers(self) -> None:
        """Close GeoIP database readers after the run.

        Closing readers between runs allows database files to be
        replaced/updated without requiring service restart.
        """
        if self._geo_reader:
            self._geo_reader.close()
            self._geo_reader = None
        if self._asn_reader:
            self._asn_reader.close()
            self._asn_reader = None

    async def run(self) -> None:
        """Execute a single relay monitoring cycle.

        Performs health checks on all relays that need monitoring and stores
        the results. This method is called by run_forever() at the configured
        interval, or can be invoked directly for one-shot monitoring.

        Workflow:
            1. Open GeoIP database readers (if geo checks enabled)
            2. Publish Kind 10166 announcement (max once per hour)
            3. Fetch relays needing checks from database
            4. Process relays in parallel with concurrency limits
            5. Batch insert metadata results to database
            6. Save checkpoints for successfully checked relays
            7. Close GeoIP readers to allow database updates

        The method processes relays in chunks to limit memory usage from
        pending asyncio tasks. Each relay check includes:
            - NIP-11 info document fetch
            - WebSocket connectivity test (open/read/write)
            - DNS resolution timing
            - SSL certificate validation
            - IP geolocation

        Results are stored as RelayMetadata records and optionally published
        as Kind 30166 events to the monitored relay or configured relays.

        Raises:
            Exception: Propagated from database operations or network failures.
                Individual relay check failures are caught and logged.

        Note:
            Supports graceful shutdown - checks self.is_running between chunks
            and exits early if shutdown is requested.
        """
        cycle_start = time.time()
        self._checked_relays = 0
        self._successful_checks = 0
        self._failed_checks = 0

        # Open GeoIP readers at start of run (closed at end to allow DB updates)
        self._open_geo_readers()

        try:
            # Publish Kind 10166 announcement if publishing enabled (once per hour max)
            if (
                self._config.publishing.enabled
                and self._config.publishing.destination != "database_only"
            ):
                if time.time() - self._last_announcement > ANNOUNCE_INTERVAL:
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
            chunk_size = max(
                self._config.concurrency.max_parallel * CHUNK_MULTIPLIER, CHUNK_MIN_SIZE
            )

            for chunk_start in range(0, len(relays), chunk_size):
                # Check for graceful shutdown between chunks
                if not self.is_running:
                    self._logger.info(
                        "monitor_interrupted", reason="shutdown", processed=chunk_start
                    )
                    break

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

                for relay, result in zip(task_relays, results, strict=False):
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
                ("monitor", "checkpoint", url, {"last_check_at": now})
                for url in successful_relay_urls
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
        finally:
            # Close GeoIP readers to allow database file updates between runs
            self._close_geo_readers()

    async def _fetch_relays_to_check(self) -> list[Relay]:
        """Fetch relays that need health checking from the database.

        Uses a SQL LEFT JOIN to efficiently filter relays based on their
        last check timestamp stored in the service_data table. This approach
        avoids loading all checkpoints into Python memory.

        Selection criteria:
            - Relays never checked before (no checkpoint record)
            - Relays not checked within min_age_since_check seconds

        Overlay network filtering:
            - Tor, I2P, and Loki relays are skipped if their respective
              proxy is not enabled in the network configuration
            - Skipped counts are logged at debug level

        Returns:
            List of Relay objects ordered by discovery time (oldest first).
            Empty list if no relays need checking.

        Note:
            Invalid relay URLs (malformed or unparseable) are silently
            skipped and logged at debug level.
        """
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

        skipped_overlay: dict[str, int] = {}  # Track skipped relays by network

        for row in rows:
            url_str = row["url"]

            try:
                relay = Relay(url_str, discovered_at=row["discovered_at"])
                # Filter overlay network relays if proxy disabled
                overlay_networks = (NetworkType.TOR, NetworkType.I2P, NetworkType.LOKI)
                if relay.network in overlay_networks:
                    if not self._config.networks.is_enabled(relay.network):
                        skipped_overlay[relay.network] = skipped_overlay.get(relay.network, 0) + 1
                        continue
                relays.append(relay)
            except Exception:
                self._logger.debug("invalid_relay_url", url=url_str)

        if skipped_overlay:
            self._logger.debug("skipped_overlay_relays", **skipped_overlay)

        self._logger.debug("relays_to_check", count=len(relays))
        return relays

    async def _process_relay(
        self, relay: Relay, semaphore: asyncio.Semaphore
    ) -> list[RelayMetadata]:
        """Perform health checks on a single relay with concurrency control.

        Executes all configured health checks for the relay and collects
        metadata results. Uses a semaphore to limit concurrent checks
        and prevent overwhelming network resources.

        Check sequence:
            1. NIP-11: Fetch relay information document via HTTP
            2. NIP-66: Test WebSocket connectivity (open/read/write)
            3. DNS: Measure resolution time (if clearnet)
            4. SSL: Validate certificate chain (if wss://)
            5. Geo: Geolocate relay IP address

        After checks complete, optionally publishes a Kind 30166 relay
        discovery event to the monitored relay or configured relays.

        Args:
            relay: The relay to check.
            semaphore: Asyncio semaphore for concurrency limiting.

        Returns:
            List of RelayMetadata records containing check results.
            Returns empty list if all checks fail or raise exceptions.

        Note:
            All exceptions are caught internally to prevent one failed
            relay from affecting others. Failures are logged and the
            failed_checks counter is incremented.
        """
        async with semaphore:
            # Race condition fix: Protect counter increment with lock
            async with self._metrics_lock:
                self._checked_relays += 1

            # Get timeout from unified network config
            timeout = self._config.networks.get(relay.network).timeout

            nip11: Nip11 | None = None
            nip66: Nip66 | None = None
            metadata_records: list[RelayMetadata] = []

            try:
                # NIP-11 check
                if self._config.checks.nip11:
                    nip11 = await fetch_nip11(
                        relay, timeout, self._config.checks.nip11_max_size, self._config.networks
                    )
                    if nip11:
                        metadata_records.append(nip11.to_relay_metadata())

                # NIP-66 test (DNS, SSL, Geo, Connection)
                # Get keys for write test if enabled
                keys = self._keys if self._config.checks.write else None

                # Get proxy URL for overlay networks
                proxy_url = self._config.networks.get_proxy_url(relay.network)

                # Run all NIP-66 tests via Nip66.test()
                nip66 = await Nip66.test(
                    relay=relay,
                    timeout=timeout,
                    keys=keys,
                    city_reader=self._geo_reader,
                    asn_reader=self._asn_reader,
                    run_geo=self._config.checks.geo,
                    proxy_url=proxy_url,
                )

                # Add nip66 metadata records (rtt and optionally ssl/geo)
                if nip66:
                    metadata_records.extend(r for r in nip66.to_relay_metadata() if r)

                # Publish Kind 30166 event if enabled
                if (
                    self._config.publishing.enabled
                    and self._config.publishing.destination != "database_only"
                    and self._keys
                ):
                    await self._publish_relay_discovery(relay, nip11, nip66)

                # Race condition fix: Protect counter increments with lock
                if (nip66 and nip66.is_openable) or nip11:
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
        """Insert a batch of relay metadata records into the database.

        Uses the Brotr.insert_relay_metadata() method which handles
        content-addressed deduplication via SHA-256 hashing. Metadata
        is stored in the unified metadata table with relay associations
        in relay_metadata.

        Args:
            batch: List of RelayMetadata records to insert. Each record
                contains the relay URL, metadata type (nip11, nip66_rtt,
                nip66_ssl, nip66_geo), and the metadata content.

        Note:
            Errors are caught and logged rather than raised to prevent
            database issues from stopping the monitoring cycle. The
            batch_size configuration controls how often this is called.
        """
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
        self, relay: Relay, nip11: Nip11 | None, nip66: Nip66 | None
    ) -> None:
        """Publish a Kind 30166 relay discovery event to the Nostr network.

        Creates and signs a NIP-66 relay discovery event containing the
        relay's metadata and health check results. The event is published
        to either the monitored relay itself or to configured relay URLs.

        Event structure:
            - Kind: 30166 (parametrized replaceable event)
            - Content: NIP-11 JSON document (if available)
            - Tags: See build_kind_30166_tags() for full tag structure

        Publishing destinations (configured via publishing.destination):
            - "monitored_relay": Publish to the relay being checked
            - "configured_relays": Publish to publishing.relays list
            - "database_only": No publishing (this method not called)

        Args:
            relay: The relay that was checked (used for URL and network type).
            nip11: Optional NIP-11 document to include as event content.
            nip66: Optional NIP-66 health results for RTT and geo tags.

        Note:
            Publishing failures are logged at debug level and do not
            raise exceptions. This prevents network issues from affecting
            the monitoring cycle.
        """
        if not self._keys:
            return

        from nostr_sdk import RelayUrl

        from utils.transport import create_client

        try:
            # Build event content (NIP-11 JSON if available)
            content = ""
            if nip11:
                content = nip11.metadata.to_db_params()[0]

            # Build tags
            tags = build_kind_30166_tags(relay, nip11, nip66)

            # Create and sign event
            builder = EventBuilder(Kind(30166), content).tags(tags)

            # Determine destination
            if self._config.publishing.destination == "monitored_relay":
                # Publish to the relay being monitored
                proxy_url = self._config.networks.get_proxy_url(relay.network)
                client = create_client(self._keys, proxy_url)
                await client.add_relay(RelayUrl.parse(relay.url))
                try:
                    await client.connect()
                    await client.send_event_builder(builder)
                finally:
                    await client.shutdown()

            elif self._config.publishing.destination == "configured_relays":
                # Publish to configured relay list
                client = create_client(self._keys)
                for url in self._config.publishing.relays:
                    try:
                        await client.add_relay(RelayUrl.parse(url))
                    except Exception:
                        pass
                try:
                    await client.connect()
                    await client.send_event_builder(builder)
                finally:
                    await client.shutdown()

        except Exception as e:
            self._logger.debug("publish_30166_failed", relay=relay.url, error=str(e))

    async def _publish_announcement(self) -> None:
        """Publish a Kind 10166 monitor announcement event to the Nostr network.

        Creates and signs a NIP-66 monitor announcement event that advertises
        this monitor's presence and capabilities. This allows other Nostr
        clients to discover active monitors and understand their methodology.

        Event structure:
            - Kind: 10166 (replaceable event, one per pubkey)
            - Content: Empty string
            - Tags: See build_kind_10166_tags() for full tag structure

        The announcement is published to all configured relays in the
        publishing.relays list. This method is rate-limited to once per
        hour (ANNOUNCE_INTERVAL) to avoid spamming the network.

        Note:
            - Requires signing keys to be configured
            - Only publishes if publishing.relays is non-empty
            - Failures are logged at warning level but do not raise
        """
        if not self._keys:
            return

        from nostr_sdk import RelayUrl

        from utils.transport import create_client

        try:
            # Build tags
            tags = build_kind_10166_tags(self._config)

            # Create and sign event
            builder = EventBuilder(Kind(10166), "").tags(tags)

            # Publish to configured relays
            if self._config.publishing.relays:
                client = create_client(self._keys)
                for url in self._config.publishing.relays:
                    try:
                        await client.add_relay(RelayUrl.parse(url))
                    except Exception:
                        pass
                try:
                    await client.connect()
                    await client.send_event_builder(builder)
                    self._logger.info("announcement_published")
                finally:
                    await client.shutdown()

        except Exception as e:
            self._logger.warning("publish_10166_failed", error=str(e), error_type=type(e).__name__)
