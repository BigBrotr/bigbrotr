"""Monitors relay health and metadata with NIP-66 compliance.

Performs connectivity tests, fetches NIP-11 documents, validates SSL certificates,
measures DNS resolution, geolocates IPs, and publishes Kind 30166/10166 events.
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, ClassVar

import geoip2.database
from nostr_sdk import EventBuilder, Filter, Keys, Kind, RelayUrl, Tag
from pydantic import BaseModel, BeforeValidator, Field, PlainSerializer, model_validator

from core.base_service import BaseService, BaseServiceConfig
from models import Nip11, Nip66, Relay, RelayMetadata
from models.relay import NetworkType
from utils.keys import KeysConfig
from utils.network import NetworkConfig
from utils.transport import create_client


if TYPE_CHECKING:
    from core.brotr import Brotr
    from models.nip11 import Nip11Limitation, Nip11RetentionEntry


def _parse_relays(v: list[str | Relay]) -> list[Relay]:
    """Parse relay URL strings into Relay objects, skipping invalid URLs."""
    relays: list[Relay] = []
    for x in v:
        if isinstance(x, Relay):
            relays.append(x)
        else:
            try:
                relays.append(Relay(x))
            except ValueError:
                pass
    return relays


RelayList = Annotated[
    list[Relay],
    BeforeValidator(_parse_relays),
    PlainSerializer(lambda v: [r.url for r in v]),
]


def _download_geolite_db(url: str, dest: Path) -> None:
    """Download a GeoLite2 database file from GitHub mirror.

    Args:
        url: Download URL for the .mmdb file.
        dest: Local path to save the database.

    Raises:
        urllib.error.URLError: If download fails.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, dest)


# =============================================================================
# Configuration
# =============================================================================


class MetadataFlags(BaseModel):
    """Which metadata types to compute/store/publish."""

    nip11: bool = Field(default=True)
    nip66_rtt: bool = Field(default=True)
    nip66_probe: bool = Field(default=True)
    nip66_ssl: bool = Field(default=True)
    nip66_geo: bool = Field(default=True)
    nip66_net: bool = Field(default=True)
    nip66_dns: bool = Field(default=True)
    nip66_http: bool = Field(default=True)

    def get_missing_from(self, superset: MetadataFlags) -> list[str]:
        """Return fields that are True in self but False in superset."""
        return [
            field
            for field in MetadataFlags.model_fields
            if getattr(self, field) and not getattr(superset, field)
        ]


class ProcessingConfig(BaseModel):
    """Processing settings including what to compute and store."""

    chunk_size: int = Field(default=100, ge=10, le=1000)
    max_relays: int | None = Field(default=None, ge=1)
    nip11_max_size: int = Field(default=1_048_576, ge=1024, le=10_485_760)
    compute: MetadataFlags = Field(default_factory=MetadataFlags)
    store: MetadataFlags = Field(default_factory=MetadataFlags)


class GeoConfig(BaseModel):
    """Geolocation database settings."""

    city_database_path: str = Field(default="static/GeoLite2-City.mmdb")
    asn_database_path: str = Field(default="static/GeoLite2-ASN.mmdb")
    city_download_url: str = Field(
        default="https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-City.mmdb"
    )
    asn_download_url: str = Field(
        default="https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-ASN.mmdb"
    )
    max_age_days: int | None = Field(default=30, ge=1)


class PublishingConfig(BaseModel):
    """Default relay list for publishing events."""

    relays: RelayList = Field(default_factory=list)


class DiscoveryConfig(BaseModel):
    """Kind 30166 relay discovery event settings."""

    enabled: bool = Field(default=True)
    interval: int = Field(default=3600, ge=60)
    include: MetadataFlags = Field(default_factory=MetadataFlags)
    # override publishing.relays
    relays: RelayList = Field(default_factory=list)


class AnnouncementConfig(BaseModel):
    """Kind 10166 monitor announcement settings."""

    enabled: bool = Field(default=True)
    interval: int = Field(default=86_400, ge=60)
    relays: RelayList = Field(default_factory=list)


class ProfileConfig(BaseModel):
    """Kind 0 profile settings."""

    enabled: bool = Field(default=False)
    interval: int = Field(default=86_400, ge=60)
    relays: RelayList = Field(default_factory=list)
    # Profile content (NIP-01)
    name: str | None = Field(default=None)
    about: str | None = Field(default=None)
    picture: str | None = Field(default=None)
    nip05: str | None = Field(default=None)
    website: str | None = Field(default=None)
    banner: str | None = Field(default=None)
    lud16: str | None = Field(default=None)


class MonitorConfig(BaseServiceConfig):
    """Monitor service configuration."""

    networks: NetworkConfig = Field(default_factory=NetworkConfig)
    keys: KeysConfig = Field(default_factory=lambda: KeysConfig.model_validate({}))
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    geo: GeoConfig = Field(default_factory=GeoConfig)
    publishing: PublishingConfig = Field(default_factory=PublishingConfig)
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    announcement: AnnouncementConfig = Field(default_factory=AnnouncementConfig)
    profile: ProfileConfig = Field(default_factory=ProfileConfig)

    @model_validator(mode="after")
    def validate_geo_databases(self) -> MonitorConfig:
        """Ensure geo databases exist, downloading from GitHub mirror if missing."""
        # Download City database if geo is enabled
        if self.processing.compute.nip66_geo:
            city_path = Path(self.geo.city_database_path)
            if not city_path.exists():
                _download_geolite_db(self.geo.city_download_url, city_path)

        # Download ASN database if net is enabled
        if self.processing.compute.nip66_net:
            asn_path = Path(self.geo.asn_database_path)
            if not asn_path.exists():
                _download_geolite_db(self.geo.asn_download_url, asn_path)

        return self

    @model_validator(mode="after")
    def validate_store_requires_compute(self) -> MonitorConfig:
        """Ensure storing requires computing."""
        errors = self.processing.store.get_missing_from(self.processing.compute)
        if errors:
            raise ValueError(
                f"Cannot store metadata that is not computed: {', '.join(errors)}. "
                "Enable in processing.compute.* or disable in processing.store.*"
            )
        return self

    @model_validator(mode="after")
    def validate_publish_requires_compute(self) -> MonitorConfig:
        """Ensure publishing requires computing."""
        if not self.discovery.enabled:
            return self
        errors = self.discovery.include.get_missing_from(self.processing.compute)
        if errors:
            raise ValueError(
                f"Cannot publish metadata that is not computed: {', '.join(errors)}. "
                "Enable in processing.compute.* or disable in discovery.include.*"
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
        - I2P (wss://*.i2p): Connections via SOCKS5 proxy (configurable)
        - Lokinet (wss://*.loki): Connections via SOCKS5 proxy (configurable)

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

    # -------------------------------------------------------------------------
    # Cursor Helpers (persistent state in service_data)
    # -------------------------------------------------------------------------

    async def _get_cursor_timestamp(self, cursor_name: str) -> float:
        """Get a cursor timestamp from service_data.

        Args:
            cursor_name: Name of the cursor (e.g., "last_announcement", "last_profile")

        Returns:
            Timestamp as float, or 0.0 if not found.
        """
        rows = await self._brotr.get_service_data("monitor", "cursor", cursor_name)
        if rows and rows[0].get("value"):
            return float(rows[0]["value"].get("timestamp", 0.0))
        return 0.0

    async def _set_cursor_timestamp(self, cursor_name: str, timestamp: float) -> None:
        """Save a cursor timestamp to service_data.

        Args:
            cursor_name: Name of the cursor
            timestamp: Timestamp to save
        """
        await self._brotr.upsert_service_data(
            [("monitor", "cursor", cursor_name, {"timestamp": timestamp})]
        )

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

        await self._update_geo_databases()
        self._open_geo_readers()

        try:
            networks = self._config.networks.get_enabled_networks()
            self._logger.info(
                "cycle_started",
                chunk_size=self._config.processing.chunk_size,
                max_relays=self._config.processing.max_relays,
                networks=networks,
            )

            # Publish profile and announcement if due
            await self._publish_profile()
            await self._publish_announcement()

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

    def _update_geo_db_if_stale(
        self, path: Path, url: str, db_name: str, max_age_seconds: float
    ) -> None:
        """Update a single GeoLite2 database if stale or missing."""
        if path.exists():
            age = time.time() - path.stat().st_mtime
            if age > max_age_seconds:
                self._logger.info("updating_geo_db", db=db_name, age_days=round(age / 86400, 1))
                _download_geolite_db(url, path)
        else:
            self._logger.info("downloading_geo_db", db=db_name)
            _download_geolite_db(url, path)

    async def _update_geo_databases(self) -> None:
        """Update GeoLite2 databases if stale based on max_age_days.

        Checks file modification time against configured max_age_days threshold.
        Downloads from configured URLs if database files are stale or missing.
        Set max_age_days to None to disable automatic updates.
        """
        compute = self._config.processing.compute
        if not compute.nip66_geo and not compute.nip66_net:
            return

        max_age_days = self._config.geo.max_age_days
        if max_age_days is None:
            return
        max_age_seconds = max_age_days * 86400

        if compute.nip66_geo:
            self._update_geo_db_if_stale(
                Path(self._config.geo.city_database_path),
                self._config.geo.city_download_url,
                "city",
                max_age_seconds,
            )

        if compute.nip66_net:
            self._update_geo_db_if_stale(
                Path(self._config.geo.asn_database_path),
                self._config.geo.asn_download_url,
                "asn",
                max_age_seconds,
            )

    def _open_geo_readers(self) -> None:
        """Open GeoIP database readers for the current run.

        Readers are opened at the start of each run() cycle to allow
        database files to be updated between runs without restarting.
        """
        if self._config.processing.compute.nip66_geo:
            self._geo_reader = geoip2.database.Reader(self._config.geo.city_database_path)

        if self._config.processing.compute.nip66_net:
            self._asn_reader = geoip2.database.Reader(self._config.geo.asn_database_path)

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

        threshold = int(self._start_time) - self._config.discovery.interval

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
        threshold = int(self._start_time) - self._config.discovery.interval

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
                compute = self._config.processing.compute
                store = self._config.processing.store

                # NIP-11 check
                if compute.nip11:
                    nip11 = await Nip11.fetch(
                        relay,
                        timeout=timeout,
                        max_size=self._config.processing.nip11_max_size,
                        proxy_url=proxy_url,
                    )
                    if nip11 and store.nip11:
                        metadata_records.append(nip11.to_relay_metadata())

                # NIP-66 tests (RTT, Probe, SSL, Geo, Net, DNS, HTTP)
                needs_rtt_probe = compute.nip66_rtt or compute.nip66_probe
                keys = self._keys if needs_rtt_probe else None
                event_builder = EventBuilder.text_note("nip66-test") if needs_rtt_probe else None
                read_filter = Filter().limit(1) if needs_rtt_probe else None
                nip66 = await Nip66.test(
                    relay=relay,
                    timeout=timeout,
                    keys=keys,
                    event_builder=event_builder,
                    read_filter=read_filter,
                    city_reader=self._geo_reader,
                    asn_reader=self._asn_reader,
                    run_rtt=compute.nip66_rtt,
                    run_probe=compute.nip66_probe,
                    run_ssl=compute.nip66_ssl,
                    run_geo=compute.nip66_geo,
                    run_net=compute.nip66_net,
                    run_dns=compute.nip66_dns,
                    run_http=compute.nip66_http,
                    proxy_url=proxy_url,
                )
                if nip66:
                    meta = nip66.to_relay_metadata()
                    if meta.rtt and store.nip66_rtt:
                        metadata_records.append(meta.rtt)
                    if meta.probe and store.nip66_probe:
                        metadata_records.append(meta.probe)
                    if meta.ssl and store.nip66_ssl:
                        metadata_records.append(meta.ssl)
                    if meta.geo and store.nip66_geo:
                        metadata_records.append(meta.geo)
                    if meta.net and store.nip66_net:
                        metadata_records.append(meta.net)
                    if meta.dns and store.nip66_dns:
                        metadata_records.append(meta.dns)
                    if meta.http and store.nip66_http:
                        metadata_records.append(meta.http)

                # Publish Kind 30166
                await self._publish_relay_discovery(relay, nip11, nip66)

                # Log result
                has_rtt_open = (
                    nip66
                    and nip66.rtt_metadata
                    and nip66.rtt_metadata.data.get("rtt_open") is not None
                )
                if has_rtt_open or nip11:
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
        """
        now = int(time.time())

        # Insert metadata for successful checks
        if successful:
            metadata = [m for _, metadata_list in successful for m in metadata_list]
            if metadata:
                try:
                    count = await self._brotr.insert_relay_metadata(metadata)
                    self._logger.debug("metadata_inserted", count=count)
                except Exception as e:
                    self._logger.error("metadata_insert_failed", error=str(e), count=len(metadata))

        # Save checkpoints for all checked relays (both successful and failed)
        all_relays = [relay for relay, _ in successful] + failed
        if all_relays:
            checkpoints = [
                ("monitor", "checkpoint", relay.url, {"last_check_at": now}) for relay in all_relays
            ]
            try:
                await self._brotr.upsert_service_data(checkpoints)
            except Exception as e:
                self._logger.error("checkpoint_save_failed", error=str(e))

    # -------------------------------------------------------------------------
    # Publishing
    # -------------------------------------------------------------------------

    async def _publish_event(self, builder: EventBuilder, relays: list[Relay]) -> None:
        """Publish an event to the specified relays."""
        client = create_client(self._keys)
        for relay in relays:
            await client.add_relay(RelayUrl.parse(relay.url))
        try:
            await client.connect()
            await client.send_event_builder(builder)
        finally:
            await client.shutdown()

    def _get_discovery_relays(self) -> list[Relay]:
        return self._config.discovery.relays or self._config.publishing.relays

    def _get_announcement_relays(self) -> list[Relay]:
        return self._config.announcement.relays or self._config.publishing.relays

    def _get_profile_relays(self) -> list[Relay]:
        return self._config.profile.relays or self._config.publishing.relays

    async def _publish_announcement(self) -> None:
        """Publish Kind 10166 announcement if due.

        Rate-limited to once per interval. Timestamp persisted in service_data.
        """
        ann = self._config.announcement
        if not ann.enabled or not self._get_announcement_relays() or self._keys is None:
            return

        last_announcement = await self._get_cursor_timestamp("last_announcement")
        elapsed = time.time() - last_announcement
        if elapsed < ann.interval:
            return

        try:
            builder = self._build_kind_10166()
            await self._publish_event(builder, self._get_announcement_relays())
            self._logger.info("announcement_published")
            await self._set_cursor_timestamp("last_announcement", time.time())
        except Exception as e:
            self._logger.warning("announcement_failed", error=str(e))

    async def _publish_profile(self) -> None:
        """Publish Kind 0 profile if due.

        Rate-limited to once per interval. Timestamp persisted in service_data.
        """
        profile = self._config.profile
        if not profile.enabled or not self._get_profile_relays() or self._keys is None:
            return

        last_profile = await self._get_cursor_timestamp("last_profile")
        elapsed = time.time() - last_profile
        if elapsed < profile.interval:
            return

        try:
            builder = self._build_kind_0()
            await self._publish_event(builder, self._get_profile_relays())
            self._logger.info("profile_published")
            await self._set_cursor_timestamp("last_profile", time.time())
        except Exception as e:
            self._logger.warning("profile_failed", error=str(e))

    async def _publish_relay_discovery(
        self, relay: Relay, nip11: Nip11 | None, nip66: Nip66 | None
    ) -> None:
        """Publish a Kind 30166 relay discovery event if enabled."""
        disc = self._config.discovery
        if not disc.enabled or not self._get_discovery_relays() or self._keys is None:
            return

        try:
            builder = self._build_kind_30166(relay, nip11, nip66)
            await self._publish_event(builder, self._get_discovery_relays())
        except Exception as e:
            self._logger.debug("publish_30166_failed", error=str(e))

    # -------------------------------------------------------------------------
    # Event Builders
    # -------------------------------------------------------------------------

    def _build_kind_0(self) -> EventBuilder:
        """Build Kind 0 profile event."""
        profile = self._config.profile
        profile_data: dict[str, str] = {}
        if profile.name:
            profile_data["name"] = profile.name
        if profile.about:
            profile_data["about"] = profile.about
        if profile.picture:
            profile_data["picture"] = profile.picture
        if profile.nip05:
            profile_data["nip05"] = profile.nip05
        if profile.website:
            profile_data["website"] = profile.website
        if profile.banner:
            profile_data["banner"] = profile.banner
        if profile.lud16:
            profile_data["lud16"] = profile.lud16
        return EventBuilder(Kind(0), json.dumps(profile_data))

    def _build_kind_10166(self) -> EventBuilder:
        """Build Kind 10166 monitor announcement event."""
        timeout_ms = str(int(self._config.networks.clearnet.timeout * 1000))
        include = self._config.discovery.include

        tags = [Tag.parse(["frequency", str(int(self._config.interval))])]

        # Timeout tags per check type
        if include.nip66_rtt:
            tags.append(Tag.parse(["timeout", "open", timeout_ms]))
            tags.append(Tag.parse(["timeout", "read", timeout_ms]))
            tags.append(Tag.parse(["timeout", "write", timeout_ms]))
        if include.nip11:
            tags.append(Tag.parse(["timeout", "nip11", timeout_ms]))
        if include.nip66_ssl:
            tags.append(Tag.parse(["timeout", "ssl", timeout_ms]))

        # Check type tags (c)
        if include.nip66_rtt:
            tags.append(Tag.parse(["c", "open"]))
            tags.append(Tag.parse(["c", "read"]))
            tags.append(Tag.parse(["c", "write"]))
        if include.nip11:
            tags.append(Tag.parse(["c", "nip11"]))
        if include.nip66_ssl:
            tags.append(Tag.parse(["c", "ssl"]))
        if include.nip66_geo:
            tags.append(Tag.parse(["c", "geo"]))
        if include.nip66_net:
            tags.append(Tag.parse(["c", "net"]))

        return EventBuilder(Kind(10166), "").tags(tags)

    def _build_kind_30166(
        self, relay: Relay, nip11: Nip11 | None, nip66: Nip66 | None
    ) -> EventBuilder:
        """Build Kind 30166 relay discovery event."""
        include = self._config.discovery.include
        content = nip11.metadata.to_db_params()[0] if nip11 else ""
        tags = [
            Tag.parse(["d", relay.url]),
            Tag.parse(["n", relay.network.value]),
        ]

        # NIP-66 RTT tags
        if nip66 and nip66.rtt_metadata and include.nip66_rtt:
            rtt_data = nip66.rtt_metadata.data
            if rtt_data.get("rtt_open") is not None:
                tags.append(Tag.parse(["rtt-open", str(rtt_data["rtt_open"])]))
            if rtt_data.get("rtt_read") is not None:
                tags.append(Tag.parse(["rtt-read", str(rtt_data["rtt_read"])]))
            if rtt_data.get("rtt_write") is not None:
                tags.append(Tag.parse(["rtt-write", str(rtt_data["rtt_write"])]))

        # NIP-66 SSL tags
        if nip66 and nip66.ssl_metadata and include.nip66_ssl:
            ssl_data = nip66.ssl_metadata.data
            ssl_valid = ssl_data.get("ssl_valid")
            if ssl_valid is not None:
                tags.append(Tag.parse(["ssl", "valid" if ssl_valid else "!valid"]))
            ssl_expires = ssl_data.get("ssl_expires")
            if ssl_expires is not None:
                tags.append(Tag.parse(["ssl-expires", str(ssl_expires)]))
            ssl_issuer = ssl_data.get("ssl_issuer")
            if ssl_issuer:
                tags.append(Tag.parse(["ssl-issuer", ssl_issuer]))

        # NIP-66 Network tags
        if nip66 and nip66.net_metadata and include.nip66_net:
            net_data = nip66.net_metadata.data
            net_ip = net_data.get("net_ip")
            if net_ip:
                tags.append(Tag.parse(["net-ip", net_ip]))
            net_ipv6 = net_data.get("net_ipv6")
            if net_ipv6:
                tags.append(Tag.parse(["net-ipv6", net_ipv6]))
            net_asn = net_data.get("net_asn")
            if net_asn is not None:
                tags.append(Tag.parse(["net-asn", str(net_asn)]))
            net_asn_org = net_data.get("net_asn_org")
            if net_asn_org:
                tags.append(Tag.parse(["net-asn-org", net_asn_org]))

        # NIP-66 Geo tags
        if nip66 and nip66.geo_metadata and include.nip66_geo:
            geo_data = nip66.geo_metadata.data
            geohash = geo_data.get("geohash")
            if geohash:
                tags.append(Tag.parse(["g", geohash]))
            geo_country = geo_data.get("geo_country")
            if geo_country:
                tags.append(Tag.parse(["geo-country", geo_country]))
            geo_city = geo_data.get("geo_city")
            if geo_city:
                tags.append(Tag.parse(["geo-city", geo_city]))
            geo_lat = geo_data.get("geo_lat")
            if geo_lat is not None:
                tags.append(Tag.parse(["geo-lat", str(geo_lat)]))
            geo_lon = geo_data.get("geo_lon")
            if geo_lon is not None:
                tags.append(Tag.parse(["geo-lon", str(geo_lon)]))
            geo_tz = geo_data.get("geo_tz")
            if geo_tz:
                tags.append(Tag.parse(["geo-tz", geo_tz]))

        # NIP-11 capability tags
        if nip11 and include.nip11:
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

        return EventBuilder(Kind(30166), content).tags(tags)

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
