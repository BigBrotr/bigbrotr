"""Monitors relay health and metadata with NIP-66 compliance.

Performs connectivity tests, fetches NIP-11 documents, validates SSL certificates,
measures DNS resolution, geolocates IPs, and publishes Kind 30166/10166 events.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Literal

import geoip2.database
from nostr_sdk import EventBuilder, Keys, Kind, RelayUrl, Tag
from pydantic import BaseModel, Field, model_validator

from core.base_service import BaseService, BaseServiceConfig
from models import Nip11, Nip66, Relay, RelayMetadata
from models.relay import NetworkType
from utils.keys import KeysConfig
from utils.network import NetworkConfig
from utils.transport import create_client


if TYPE_CHECKING:
    from core.brotr import Brotr
    from models.nip11 import Nip11Limitation, Nip11RetentionEntry


# =============================================================================
# Configuration
# =============================================================================


class ProcessingConfig(BaseModel):
    """Chunk processing settings."""

    chunk_size: int = Field(default=100, ge=10, le=1000)
    max_relays: int | None = Field(default=None, ge=1)
    nip11_max_size: int = Field(default=1_048_576, ge=1024, le=10_485_760)


class MetadataFlags(BaseModel):
    """Which metadata types to store/publish."""

    nip11: bool = Field(default=True)
    nip66_rtt: bool = Field(default=True)
    nip66_ssl: bool = Field(default=True)
    nip66_geo: bool = Field(default=True)
    nip66_dns: bool = Field(default=True)
    nip66_http: bool = Field(default=True)


class GeoConfig(BaseModel):
    """Geolocation database settings."""

    city_database_path: str = Field(default="static/GeoLite2-City.mmdb")
    asn_database_path: str = Field(default="static/GeoLite2-ASN.mmdb")
    update_frequency: Literal["monthly", "weekly", "none"] = Field(default="monthly")


class DiscoveryConfig(BaseModel):
    """Kind 30166 relay discovery event settings."""

    enabled: bool = Field(default=True)
    interval: int = Field(default=3600, ge=60)
    include: MetadataFlags = Field(default_factory=MetadataFlags)
    monitored_relay: bool = Field(default=True)
    configured_relays: bool = Field(default=True)
    relays: list[str] = Field(default_factory=list)


class AnnouncementConfig(BaseModel):
    """Kind 10166 monitor announcement settings."""

    enabled: bool = Field(default=True)
    interval: int = Field(default=86_400, ge=60)
    relays: list[str] = Field(default_factory=list)


class ProfileConfig(BaseModel):
    """Kind 0 profile settings."""

    enabled: bool = Field(default=False)
    interval: int = Field(default=86_400, ge=60)
    relays: list[str] = Field(default_factory=list)


class PublishingConfig(BaseModel):
    """All publishing settings."""

    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    announcement: AnnouncementConfig = Field(default_factory=AnnouncementConfig)
    profile: ProfileConfig = Field(default_factory=ProfileConfig)


class MonitorConfig(BaseServiceConfig):
    """Monitor service configuration."""

    networks: NetworkConfig = Field(default_factory=NetworkConfig)
    keys: KeysConfig = Field(default_factory=lambda: KeysConfig.model_validate({}))
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    storing: MetadataFlags = Field(default_factory=MetadataFlags)
    geo: GeoConfig = Field(default_factory=GeoConfig)
    publishing: PublishingConfig = Field(default_factory=PublishingConfig)

    @model_validator(mode="after")
    def validate_geo_databases(self) -> MonitorConfig:
        """Fail-fast: If geo check enabled, databases MUST exist."""
        if not self.storing.nip66_geo:
            return self

        city_path = Path(self.geo.city_database_path)
        if not city_path.exists():
            raise ValueError(
                f"geo.city_database_path not found: {city_path}. "
                "Download GeoLite2-City.mmdb or set storing.nip66_geo=false."
            )

        asn_path = Path(self.geo.asn_database_path)
        if not asn_path.exists():
            raise ValueError(
                f"geo.asn_database_path not found: {asn_path}. "
                "Download GeoLite2-ASN.mmdb or set storing.nip66_geo=false."
            )

        return self

    @model_validator(mode="after")
    def validate_publish_requires_store(self) -> MonitorConfig:
        """Ensure publishing a check requires storing it."""
        if not self.publishing.discovery.enabled:
            return self

        checks = self.storing
        pub_checks = self.publishing.discovery.include
        errors = []

        if pub_checks.nip11 and not checks.nip11:
            errors.append("nip11")
        if pub_checks.nip66_rtt and not checks.nip66_rtt:
            errors.append("nip66_rtt")
        if pub_checks.nip66_ssl and not checks.nip66_ssl:
            errors.append("nip66_ssl")
        if pub_checks.nip66_geo and not checks.nip66_geo:
            errors.append("nip66_geo")
        if pub_checks.nip66_dns and not checks.nip66_dns:
            errors.append("nip66_dns")
        if pub_checks.nip66_http and not checks.nip66_http:
            errors.append("nip66_http")

        if errors:
            raise ValueError(
                f"Cannot publish checks that are not stored: {', '.join(errors)}. "
                "Enable in storing.* or disable in publishing.discovery.include.*"
            )

        return self


# =============================================================================
# Service
# =============================================================================


class Monitor(BaseService[MonitorConfig]):
    """Monitors relay health and metadata with full NIP-66 compliance.

    This service performs comprehensive health checks on relays and stores the
    results as metadata. It can optionally publish Kind 30166 relay discovery
    events and Kind 10166 monitor announcements to the Nostr network.

    Health Checks:
        - Open: WebSocket connection test
        - Read: REQ/EOSE subscription test
        - Write: EVENT/OK publication test (requires signing keys)
        - NIP-11: Fetch relay information document
        - SSL: Validate certificate chain and expiry
        - DNS: Measure resolution time
        - Geo: Geolocate relay IP address

    Workflow:
        1. Reset cycle state and initialize per-network concurrency semaphores
        2. Publish Kind 10166 announcement (max once per configured interval)
        3. Fetch relays needing checks (not checked within min_age_since_check)
        4. Process relays in configurable chunks:
           a. Fetch chunk ordered by discovered_at ASC
           b. Run health checks concurrently (respecting network semaphores)
           c. Batch insert metadata results to database
        5. Save checkpoints for successfully checked relays
        6. Emit metrics and log completion statistics

    Network Support:
        - Clearnet (wss://): Direct WebSocket connections
        - Tor (wss://*.onion): Connections via SOCKS5 proxy (configurable)
        - I2P (wss://*.i2p): Connections via HTTP proxy (configurable)

    Attributes:
        SERVICE_NAME: Service identifier for configuration and logging.
        CONFIG_CLASS: Pydantic configuration model class.
    """

    SERVICE_NAME: ClassVar[str] = "monitor"
    CONFIG_CLASS: ClassVar[type[MonitorConfig]] = MonitorConfig

    def __init__(self, brotr: Brotr, config: MonitorConfig | None = None) -> None:
        super().__init__(brotr=brotr, config=config)
        self._config: MonitorConfig
        self._keys: Keys = self._config.keys.keys
        self._semaphores: dict[NetworkType, asyncio.Semaphore] = {}
        # GeoIP readers (opened/closed each cycle to allow DB updates)
        self._geo_reader: geoip2.database.Reader | None = None
        self._asn_reader: geoip2.database.Reader | None = None
        # Cycle state (reset at start of each run)
        self._start_time: float = 0.0
        self._total_relays: int = 0
        self._checked: int = 0
        self._successful: int = 0
        self._failed: int = 0
        self._chunks: int = 0
        self._last_announcement: float = 0.0

    # -------------------------------------------------------------------------
    # Main Cycle
    # -------------------------------------------------------------------------

    async def run(self) -> None:
        """Execute one complete monitoring cycle.

        Orchestrates the full monitoring workflow: announcement, count, process,
        and metrics emission. Each cycle processes relays in chunks fetched
        directly from the database to manage memory.

        The cycle respects the `is_running` flag and will exit early if the service
        is stopped. It also respects `max_relays` configuration to limit the
        number of relays processed per cycle.

        Raises:
            Exception: Database errors are logged but not raised to allow the
                service to continue with subsequent cycles.
        """
        self._reset_cycle_state()
        self._init_semaphores()
        self._open_geo_readers()

        try:
            networks = self._config.networks.get_enabled_networks()
            self._logger.info(
                "cycle_started",
                chunk_size=self._config.processing.chunk_size,
                max_relays=self._config.processing.max_relays,
                networks=networks,
            )

            # Publish announcement if due
            await self._maybe_publish_announcement()

            # Count relays needing checks
            self._total_relays = await self._count_relays(networks)

            self._logger.info("relays_available", total=self._total_relays)
            self._emit_metrics()

            # Process all relays (fetching chunks from DB)
            await self._process_all(networks)

            self._emit_metrics()
            self._logger.info(
                "cycle_completed",
                checked=self._checked,
                successful=self._successful,
                failed=self._failed,
                chunks=self._chunks,
                duration_s=round(time.time() - self._start_time, 1),
            )
        finally:
            self._close_geo_readers()

    def _reset_cycle_state(self) -> None:
        """Reset all cycle counters and timers for a fresh monitoring run.

        Called at the start of each run() to ensure clean state. This prevents
        metrics from previous cycles from carrying over and ensures accurate
        duration calculations.

        Resets:
            _start_time: Current timestamp for duration tracking.
            _total_relays: Total relays available count.
            _checked: Relays processed count.
            _successful: Successfully checked relay count.
            _failed: Failed check relay count.
            _chunks: Number of chunks processed.
        """
        self._start_time = time.time()
        self._total_relays = 0
        self._checked = 0
        self._successful = 0
        self._failed = 0
        self._chunks = 0

    def _init_semaphores(self) -> None:
        """Initialize per-network concurrency semaphores.

        Creates an asyncio.Semaphore for each network type (clearnet, tor, i2p)
        to limit concurrent health check connections. This prevents overwhelming
        network resources, especially important for Tor where too many simultaneous
        connections can degrade performance.

        The max_tasks value for each network is read from the configuration's
        networks section. Semaphores are recreated each cycle to pick up any
        configuration changes.
        """
        self._semaphores = {
            network: asyncio.Semaphore(self._config.networks.get(network).max_tasks)
            for network in NetworkType
        }

    def _open_geo_readers(self) -> None:
        """Open GeoIP database readers for the current run.

        Readers are opened at the start of each run() cycle to allow
        database files to be updated between runs without restarting.
        """
        if not self._config.storing.nip66_geo:
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

    # -------------------------------------------------------------------------
    # Metrics
    # -------------------------------------------------------------------------

    def _emit_metrics(self) -> None:
        """Emit Prometheus metrics reflecting current cycle state.

        Updates gauge metrics for monitoring dashboards:
            - total_relays: Total relays available at cycle start
            - checked: Relays processed (cumulative in cycle)
            - successful: Relays that passed checks (cumulative in cycle)
            - failed: Relays that failed checks (cumulative in cycle)

        Called after fetching relays, after each chunk, and at cycle completion
        to provide real-time visibility into monitoring progress.
        """
        self.set_gauge("total_relays", self._total_relays)
        self.set_gauge("checked", self._checked)
        self.set_gauge("successful", self._successful)
        self.set_gauge("failed", self._failed)

    # -------------------------------------------------------------------------
    # Counting
    # -------------------------------------------------------------------------

    async def _count_relays(self, networks: list[str]) -> int:
        """Count the total number of relays needing checks for enabled networks.

        Queries the database to count relays whose last check timestamp is older
        than the configured threshold. This count is used for progress reporting
        and metrics.

        Args:
            networks: List of enabled network type strings (e.g., ['clearnet', 'tor']).

        Returns:
            Total count of relays needing checks.
            Returns 0 if no relays need checking or if the query fails.
        """
        if not networks:
            self._logger.warning("no_networks_enabled")
            return 0

        threshold = int(self._start_time) - self._config.publishing.discovery.interval

        row = await self._brotr.pool.fetchrow(
            """
            SELECT COUNT(*)::int AS count
            FROM relays r
            LEFT JOIN service_data sd ON
                sd.service_name = 'monitor'
                AND sd.data_type = 'checkpoint'
                AND sd.data_key = r.url
            WHERE
                r.network = ANY($1)
                AND (sd.data_key IS NULL OR (sd.data->>'last_check_at')::BIGINT < $2)
            """,
            networks,
            threshold,
            timeout=self._brotr.config.timeouts.query,
        )
        return row["count"] if row else 0

    # -------------------------------------------------------------------------
    # Processing
    # -------------------------------------------------------------------------

    async def _process_all(self, networks: list[str]) -> None:
        """Process all pending relays in configurable chunks.

        Iteratively fetches and checks relays until one of these conditions:
            - No more relays remain
            - max_relays limit is reached (if configured)
            - Service is stopped (is_running becomes False)

        Each iteration fetches a chunk from the database, checks them concurrently,
        persists the results, and emits progress metrics. Chunk size is configurable
        to balance memory usage against database round-trips.

        Args:
            networks: List of enabled network type strings to process.
                If empty, logs a warning and returns immediately.
        """
        if not networks:
            self._logger.warning("no_networks_enabled")
            return

        max_relays = self._config.processing.max_relays
        chunk_size = self._config.processing.chunk_size

        while self.is_running:
            # Calculate limit for this chunk
            if max_relays is not None:
                budget = max_relays - self._checked
                if budget <= 0:
                    self._logger.debug("max_relays_reached", limit=max_relays)
                    break
                limit = min(chunk_size, budget)
            else:
                limit = chunk_size

            # Fetch and process chunk
            relays = await self._fetch_chunk(networks, limit)
            if not relays:
                self._logger.debug("no_more_relays")
                break

            self._chunks += 1
            successful, failed = await self._check_chunk(relays)
            await self._persist_results(successful, failed)

            self._emit_metrics()
            self._logger.info(
                "chunk_completed",
                chunk=self._chunks,
                successful=len(successful),
                failed=len(failed),
                remaining=self._total_relays - self._checked,
            )

    async def _fetch_chunk(self, networks: list[str], limit: int) -> list[Relay]:
        """Fetch the next chunk of relays for health checking.

        Retrieves relays from the database, ordered to prioritize:
            1. Relays never checked (no checkpoint record)
            2. Older checkpoints first (FIFO within checked relays)

        Only fetches relays with checkpoints updated before the cycle start time
        to avoid re-processing relays checked in this cycle.

        Args:
            networks: List of enabled network type strings to fetch.
            limit: Maximum number of relays to return in this chunk.

        Returns:
            List of Relay objects ready for checking. May be empty if no
            relays remain or all have been processed this cycle.
        """
        threshold = int(self._start_time) - self._config.publishing.discovery.interval

        rows = await self._brotr.pool.fetch(
            """
            SELECT r.url, r.network, r.discovered_at
            FROM relays r
            LEFT JOIN service_data sd ON
                sd.service_name = 'monitor'
                AND sd.data_type = 'checkpoint'
                AND sd.data_key = r.url
            WHERE
                r.network = ANY($1)
                AND (sd.data_key IS NULL OR (sd.data->>'last_check_at')::BIGINT < $2)
            ORDER BY
                COALESCE((sd.data->>'last_check_at')::BIGINT, 0) ASC,
                r.discovered_at ASC
            LIMIT $3
            """,
            networks,
            threshold,
            limit,
            timeout=self._brotr.config.timeouts.query,
        )

        relays: list[Relay] = []
        for row in rows:
            try:
                relays.append(Relay(row["url"], discovered_at=row["discovered_at"]))
            except Exception as e:
                self._logger.warning("parse_failed", url=row["url"], error=str(e))

        return relays

    async def _check_chunk(
        self, relays: list[Relay]
    ) -> tuple[list[tuple[Relay, list[RelayMetadata]]], list[Relay]]:
        """Check a chunk of relays concurrently.

        Creates check tasks for all relays and awaits them together
        using asyncio.gather. Each check respects network-specific
        semaphores to limit concurrency.

        Updates the cycle counters (_checked, _successful, _failed) as results
        are processed.

        Args:
            relays: List of Relay objects to check.

        Returns:
            A tuple of (successful, failed) where:
                - successful: List of (Relay, metadata_list) tuples that passed
                - failed: List of Relay objects that failed all checks
        """
        tasks = [self._check_one(r) for r in relays]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        successful: list[tuple[Relay, list[RelayMetadata]]] = []
        failed: list[Relay] = []

        for relay, result in zip(relays, results, strict=True):
            self._checked += 1
            if isinstance(result, BaseException):
                self._logger.debug("check_exception", url=relay.url, error=str(result))
                self._failed += 1
                failed.append(relay)
            elif result:
                self._successful += 1
                successful.append((relay, result))
            else:
                self._failed += 1
                failed.append(relay)

        return successful, failed

    async def _check_one(self, relay: Relay) -> list[RelayMetadata]:
        """Perform health checks on a single relay.

        Executes all configured health checks for the relay and collects
        metadata results. Uses the network-specific semaphore to limit
        concurrent connections.

        Check sequence:
            1. NIP-11: Fetch relay information document via HTTP
            2. NIP-66: Test WebSocket connectivity (open/read/write) + DNS/SSL/Geo

        After checks complete, optionally publishes a Kind 30166 relay
        discovery event to the monitored relay or configured relays.

        Args:
            relay: The relay to check.

        Returns:
            List of RelayMetadata records containing check results.
            Returns empty list if all checks fail.
        """
        semaphore = self._semaphores.get(relay.network)
        if semaphore is None:
            self._logger.warning("unknown_network", url=relay.url, network=relay.network)
            return []

        async with semaphore:
            network_config = self._config.networks.get(relay.network)
            proxy_url = self._config.networks.get_proxy_url(relay.network)
            timeout = network_config.timeout

            metadata_records: list[RelayMetadata] = []
            nip11: Nip11 | None = None
            nip66: Nip66 | None = None

            try:
                # NIP-11 check
                if self._config.storing.nip11:
                    nip11 = await Nip11.fetch(
                        relay,
                        timeout=timeout,
                        max_size=self._config.processing.nip11_max_size,
                        proxy_url=proxy_url,
                    )
                    if nip11:
                        metadata_records.append(nip11.to_relay_metadata())

                # NIP-66 tests (RTT, DNS, SSL, Geo, HTTP)
                checks = self._config.storing
                keys = self._keys if checks.nip66_rtt else None
                nip66 = await Nip66.test(
                    relay=relay,
                    timeout=timeout,
                    keys=keys,
                    city_reader=self._geo_reader,
                    asn_reader=self._asn_reader,
                    run_rtt=checks.nip66_rtt,
                    run_ssl=checks.nip66_ssl,
                    run_geo=checks.nip66_geo,
                    run_dns=checks.nip66_dns,
                    run_http=checks.nip66_http,
                    proxy_url=proxy_url,
                )
                if nip66:
                    metadata_records.extend(r for r in nip66.to_relay_metadata() if r)

                # Publish Kind 30166
                if self._should_publish_discovery():
                    await self._publish_relay_discovery(relay, nip11, nip66)

                # Log result
                if (nip66 and nip66.is_openable) or nip11:
                    self._logger.debug("check_ok", url=relay.url)
                else:
                    self._logger.debug("check_failed", url=relay.url)

                return metadata_records

            except Exception as e:
                self._logger.debug("check_error", url=relay.url, error=str(e))
                return []

    # -------------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------------

    async def _persist_results(
        self,
        successful: list[tuple[Relay, list[RelayMetadata]]],
        failed: list[Relay],
    ) -> None:
        """Persist check results to the database.

        For successful checks:
            - Inserts metadata records using content-addressed deduplication
            - Saves checkpoint with current timestamp

        For failed checks:
            - Updates checkpoint to mark the attempt (prevents immediate retry)

        Args:
            successful: List of (Relay, metadata_list) tuples that passed checks.
            failed: List of Relay objects that failed all checks.
        """
        now = int(time.time())

        # Insert metadata for successful checks
        if successful:
            metadata = []
            for _, metadata_list in successful:
                metadata.extend(metadata_list)

            if metadata:
                try:
                    count = await self._brotr.insert_relay_metadata(metadata)
                    self._logger.debug("metadata_inserted", count=count)
                except Exception as e:
                    self._logger.error("metadata_insert_failed", error=str(e), count=len(metadata))

            # Save checkpoints for successful relays
            checkpoints = [
                ("monitor", "checkpoint", relay.url, {"last_check_at": now})
                for relay, _ in successful
            ]
            try:
                await self._brotr.upsert_service_data(checkpoints)
            except Exception as e:
                self._logger.error("checkpoint_save_failed", error=str(e))

        # Update checkpoints for failed relays (to avoid immediate retry)
        if failed:
            checkpoints = [
                ("monitor", "checkpoint", relay.url, {"last_check_at": now}) for relay in failed
            ]
            try:
                await self._brotr.upsert_service_data(checkpoints)
            except Exception as e:
                self._logger.error("checkpoint_save_failed", error=str(e))

    # -------------------------------------------------------------------------
    # Publishing
    # -------------------------------------------------------------------------

    def _should_publish_discovery(self) -> bool:
        """Check if Kind 30166 publishing is enabled."""
        disc = self._config.publishing.discovery
        return (
            disc.enabled
            and (disc.monitored_relay or disc.configured_relays)
            and self._keys is not None
        )

    async def _maybe_publish_announcement(self) -> None:
        """Publish Kind 10166 announcement if due.

        Rate-limited to once per interval to avoid spamming.
        """
        ann = self._config.publishing.announcement
        if not ann.enabled or not ann.relays or self._keys is None:
            return

        elapsed = time.time() - self._last_announcement
        if elapsed < ann.interval:
            return

        await self._publish_announcement()
        self._last_announcement = time.time()

    async def _publish_announcement(self) -> None:
        """Publish a Kind 10166 monitor announcement event.

        Creates and signs a NIP-66 monitor announcement that advertises
        this monitor's presence and capabilities to the Nostr network.

        Event structure:
            - Kind: 10166 (replaceable event, one per pubkey)
            - Content: Empty string
            - Tags: frequency, timeout, check types performed
        """
        ann = self._config.publishing.announcement

        try:
            tags = self._build_10166_tags()
            builder = EventBuilder(Kind(10166), "").tags(tags)

            client = create_client(self._keys)
            for url in ann.relays:
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
            self._logger.warning("announcement_failed", error=str(e))

    async def _publish_relay_discovery(
        self, relay: Relay, nip11: Nip11 | None, nip66: Nip66 | None
    ) -> None:
        """Publish a Kind 30166 relay discovery event.

        Creates and signs a NIP-66 relay discovery event containing the
        relay's metadata and health check results. Publishes to monitored
        relay, configured relays, or both based on publishing config.

        Event structure:
            - Kind: 30166 (parametrized replaceable event)
            - Content: NIP-11 JSON document (if available)
            - Tags: d (relay URL), n (network), rtt-*, g, N, R, T, k, t

        Args:
            relay: The relay that was checked.
            nip11: Optional NIP-11 document for content and capability tags.
            nip66: Optional NIP-66 results for RTT and geo tags.
        """
        disc = self._config.publishing.discovery

        # Build content (NIP-11 JSON if available)
        content = ""
        if nip11:
            content = nip11.metadata.to_db_params()[0]

        tags = self._build_30166_tags(relay, nip11, nip66)
        builder = EventBuilder(Kind(30166), content).tags(tags)

        # Publish to monitored relay
        if disc.monitored_relay:
            try:
                proxy_url = self._config.networks.get_proxy_url(relay.network)
                client = create_client(self._keys, proxy_url)
                await client.add_relay(RelayUrl.parse(relay.url))
                try:
                    await client.connect()
                    await client.send_event_builder(builder)
                finally:
                    await client.shutdown()
            except Exception as e:
                self._logger.debug("publish_30166_failed", url=relay.url, error=str(e))

        # Publish to configured relays
        if disc.configured_relays and disc.relays:
            try:
                client = create_client(self._keys)
                for url in disc.relays:
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
                self._logger.debug("publish_30166_configured_failed", error=str(e))

    # -------------------------------------------------------------------------
    # Tag Building
    # -------------------------------------------------------------------------

    def _build_10166_tags(self) -> list[Tag]:
        """Build NIP-66 Kind 10166 monitor announcement tags.

        Returns:
            List of tags: frequency, timeout values, published check types.
        """
        clearnet_timeout_ms = int(self._config.networks.clearnet.timeout * 1000)
        tags = [
            Tag.parse(["frequency", str(int(self._config.interval))]),
            Tag.parse(["timeout", "open", str(clearnet_timeout_ms)]),
            Tag.parse(["timeout", "read", str(clearnet_timeout_ms)]),
            Tag.parse(["timeout", "write", str(clearnet_timeout_ms)]),
        ]

        # Announce only checks that will be published
        pub_checks = self._config.publishing.discovery.include
        check_items = [
            ("nip11", pub_checks.nip11),
            ("rtt", pub_checks.nip66_rtt),
            ("ssl", pub_checks.nip66_ssl),
            ("geo", pub_checks.nip66_geo),
            ("dns", pub_checks.nip66_dns),
            ("http", pub_checks.nip66_http),
        ]
        for name, enabled in check_items:
            if enabled:
                tags.append(Tag.parse(["c", name]))

        return tags

    def _build_30166_tags(
        self, relay: Relay, nip11: Nip11 | None, nip66: Nip66 | None
    ) -> list[Tag]:
        """Build NIP-66 Kind 30166 relay discovery tags.

        Only includes tags for metadata types configured in publishing.discovery.include.

        Args:
            relay: The relay being described.
            nip11: Optional NIP-11 document for capability tags.
            nip66: Optional NIP-66 results for RTT and geo tags.

        Returns:
            List of tags: d, n, rtt-*, g, N, R, T, k, t.
        """
        pub_checks = self._config.publishing.discovery.include
        tags = [
            Tag.parse(["d", relay.url]),
            Tag.parse(["n", relay.network.value]),
        ]

        # NIP-66 RTT tags
        if nip66 and pub_checks.nip66_rtt:
            if nip66.rtt_open is not None:
                tags.append(Tag.parse(["rtt-open", str(nip66.rtt_open)]))
            if nip66.rtt_read is not None:
                tags.append(Tag.parse(["rtt-read", str(nip66.rtt_read)]))
            if nip66.rtt_write is not None:
                tags.append(Tag.parse(["rtt-write", str(nip66.rtt_write)]))

        # NIP-66 Geo tags
        if nip66 and pub_checks.nip66_geo and nip66.geohash:
            tags.append(Tag.parse(["g", nip66.geohash]))

        # NIP-11 capability tags
        if nip11 and pub_checks.nip11:
            if nip11.supported_nips:
                for nip in nip11.supported_nips:
                    tags.append(Tag.parse(["N", str(nip)]))

            if nip11.limitation:
                tags.extend(self._build_limitation_tags(nip11.limitation))

            if nip11.retention:
                for kind in self._extract_retention_kinds(nip11.retention):
                    tags.append(Tag.parse(["k", kind]))

            if nip11.tags:
                for topic in nip11.tags:
                    tags.append(Tag.parse(["t", topic]))

        return tags

    @staticmethod
    def _build_limitation_tags(limitation: Nip11Limitation | dict[str, Any]) -> list[Tag]:
        """Build R and T tags from NIP-11 limitation field.

        Args:
            limitation: NIP-11 limitation dict with auth, payment, etc.

        Returns:
            List of R (requirement) and T (type) tags.
        """
        tags: list[Tag] = []

        # R tags: requirements
        if limitation.get("auth_required"):
            tags.append(Tag.parse(["R", "auth"]))
        else:
            tags.append(Tag.parse(["R", "!auth"]))

        if limitation.get("payment_required"):
            tags.append(Tag.parse(["R", "payment"]))
        else:
            tags.append(Tag.parse(["R", "!payment"]))

        if limitation.get("restricted_writes"):
            tags.append(Tag.parse(["R", "writes"]))
        else:
            tags.append(Tag.parse(["R", "!writes"]))

        min_pow = limitation.get("min_pow_difficulty", 0)
        if min_pow and min_pow > 0:
            tags.append(Tag.parse(["R", "pow"]))
        else:
            tags.append(Tag.parse(["R", "!pow"]))

        # T tag: relay type
        relay_type = Monitor._determine_relay_type(limitation)
        if relay_type:
            tags.append(Tag.parse(["T", relay_type]))

        return tags

    @staticmethod
    def _determine_relay_type(limitation: Nip11Limitation | dict[str, Any]) -> str | None:
        """Determine relay type from NIP-11 limitation fields.

        Returns:
            One of: "Paid", "Private", "AuthRequired", "RestrictedWrite", "Public", or None.
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

    @staticmethod
    def _extract_retention_kinds(
        retention: list[Nip11RetentionEntry] | list[dict[str, Any]],
    ) -> list[str]:
        """Extract kind strings from NIP-11 retention field.

        Returns:
            List of kind strings with optional ! prefix for excluded kinds.
        """
        kinds: list[str] = []

        for entry in retention:
            entry_kinds: list[int | list[int]] = entry.get("kinds") or []
            is_discard = entry.get("time") == 0 or entry.get("count") == 0

            for kind in entry_kinds:
                kind_str = str(kind)
                if is_discard:
                    kinds.append(f"!{kind_str}")
                else:
                    kinds.append(kind_str)

        return kinds
