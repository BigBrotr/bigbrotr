"""Relay health monitoring service with NIP-66 compliance.

This service performs comprehensive health checks on Nostr relays and publishes
the results to the network. It supports multiple network types (clearnet, Tor,
I2P, Lokinet) and can optionally store results to the database.

Health Checks:
    - NIP-11: Fetch relay information document via HTTP
    - NIP-66 RTT: Measure WebSocket open/read/write latencies
    - NIP-66 Probe: Test read/write capabilities with actual events
    - SSL: Validate certificate chain, expiry, and issuer
    - DNS: Resolve hostname and measure resolution time
    - Geo: Geolocate relay IP using MaxMind GeoLite2 databases
    - Net: Lookup ASN information for the relay IP

Publishing:
    - Kind 30166: Relay discovery events with health check results
    - Kind 10166: Monitor announcement with capabilities and frequency
    - Kind 0: Optional monitor profile metadata
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, ClassVar, NamedTuple

import geoip2.database
from nostr_sdk import EventBuilder, Filter, Keys, Kind, RelayUrl, Tag
from pydantic import BaseModel, BeforeValidator, Field, PlainSerializer, model_validator

from core.base_service import BaseService, BaseServiceConfig
from models import Nip11, Nip66, Relay, RelayMetadata
from models.relay import NetworkType
from utils.keys import KeysConfig
from utils.network import NetworkConfig
from utils.progress import BatchProgress
from utils.transport import create_client


if TYPE_CHECKING:
    from core.brotr import Brotr


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


class CheckResult(NamedTuple):
    """Result of a single relay health check.

    Each field contains RelayMetadata if that check was run and produced data,
    or None if the check was skipped (disabled in config) or failed completely.
    A relay is considered successful if any(result) is True.

    Attributes:
        nip11: NIP-11 relay information document (name, description, pubkey, etc.).
        rtt: Round-trip times for open/read/write operations in milliseconds.
        probe: Read/write capability probe results (success/failure and reason).
        ssl: SSL certificate validation (valid, expiry timestamp, issuer).
        geo: Geolocation data (country, city, coordinates, timezone, geohash).
        net: Network information (IP address, ASN, organization).
        dns: DNS resolution data (IPs, CNAME, nameservers, reverse DNS).
        http: HTTP metadata (status code, headers, redirect chain).
    """

    nip11: RelayMetadata | None
    rtt: RelayMetadata | None
    probe: RelayMetadata | None
    ssl: RelayMetadata | None
    geo: RelayMetadata | None
    net: RelayMetadata | None
    dns: RelayMetadata | None
    http: RelayMetadata | None


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
        self._geo_reader: geoip2.database.Reader | None = None
        self._asn_reader: geoip2.database.Reader | None = None
        self._progress = BatchProgress()

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
        self._progress.reset()
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
            self._progress.total = await self._count_relays(networks)

            self._logger.info("relays_available", total=self._progress.total)
            self._emit_metrics()

            # Process all relays (fetching chunks from DB)
            await self._process_all(networks)

            self._emit_metrics()
            self._logger.info(
                "cycle_completed",
                checked=self._progress.processed,
                successful=self._progress.success,
                failed=self._progress.failure,
                chunks=self._progress.chunks,
                duration_s=self._progress.elapsed,
            )
        finally:
            self._close_geo_readers()

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
            - total: Total relays available at cycle start
            - processed: Relays processed (cumulative in cycle)
            - success: Relays that passed checks (cumulative in cycle)
            - failure: Relays that failed checks (cumulative in cycle)

        Called after fetching relays, after each chunk, and at cycle completion
        to provide real-time visibility into monitoring progress.
        """
        self.set_gauge("total", self._progress.total)
        self.set_gauge("processed", self._progress.processed)
        self.set_gauge("success", self._progress.success)
        self.set_gauge("failure", self._progress.failure)

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

        threshold = int(self._progress.started_at) - self._config.discovery.interval

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
                budget = max_relays - self._progress.processed
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

            self._progress.chunks += 1
            successful, failed = await self._check_chunk(relays)
            await self._publish_relay_discoveries(successful)
            await self._persist_results(successful, failed)

            self._emit_metrics()
            self._logger.info(
                "chunk_completed",
                chunk=self._progress.chunks,
                successful=len(successful),
                failed=len(failed),
                remaining=self._progress.remaining,
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
        threshold = int(self._progress.started_at) - self._config.discovery.interval

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
    ) -> tuple[list[tuple[Relay, CheckResult]], list[Relay]]:
        """Check a chunk of relays concurrently.

        Creates check tasks for all relays and awaits them together using
        asyncio.gather. Each check respects network-specific semaphores to
        limit concurrency. Updates progress counters as results are processed.

        Args:
            relays: List of Relay objects to check.

        Returns:
            A tuple of (successful, failed) where:
                - successful: List of (Relay, CheckResult) tuples with metadata
                - failed: List of Relay objects that failed all checks
        """
        tasks = [self._check_one(r) for r in relays]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        successful: list[tuple[Relay, CheckResult]] = []
        failed: list[Relay] = []

        for relay, result in zip(relays, results, strict=True):
            self._progress.processed += 1
            if isinstance(result, CheckResult) and any(result):
                self._progress.success += 1
                successful.append((relay, result))
            else:
                self._progress.failure += 1
                failed.append(relay)

        return successful, failed

    async def _check_one(self, relay: Relay) -> CheckResult:
        """Perform health checks on a single relay.

        Executes all configured health checks for the relay and collects
        metadata results. Uses the network-specific semaphore to limit
        concurrent connections.

        Check sequence:
            1. NIP-11: Fetch relay information document via HTTP
            2. NIP-66: Test WebSocket connectivity (open/read/write) + DNS/SSL/Geo

        Args:
            relay: The relay to check.

        Returns:
            CheckResult with all metadata fields. Fields are None if check
            was not run or failed.
        """
        empty = CheckResult(None, None, None, None, None, None, None, None)

        semaphore = self._semaphores.get(relay.network)
        if semaphore is None:
            self._logger.warning("unknown_network", url=relay.url, network=relay.network.value)
            return empty

        async with semaphore:
            network_config = self._config.networks.get(relay.network)
            proxy_url = self._config.networks.get_proxy_url(relay.network)
            timeout = network_config.timeout
            compute = self._config.processing.compute

            nip11: Nip11 | None = None
            nip66_meta = None

            try:
                # NIP-11 check
                if compute.nip11:
                    nip11 = await Nip11.fetch(
                        relay,
                        timeout=timeout,
                        max_size=self._config.processing.nip11_max_size,
                        proxy_url=proxy_url,
                    )

                # NIP-66 tests (RTT, Probe, SSL, Geo, Net, DNS, HTTP)
                needs_rtt_probe = compute.nip66_rtt or compute.nip66_probe
                keys = self._keys if needs_rtt_probe else None

                # Build addressable test event (kind 30000 with d=relay_url)
                # Replaceable per relay, can be read back to verify write
                event_builder: EventBuilder | None = None
                if needs_rtt_probe:
                    event_builder = EventBuilder(Kind(30000), "nip66-test").tags(
                        [Tag.parse(["d", relay.url])]
                    )
                    # Add POW if NIP-11 specifies minimum difficulty
                    if nip11 and nip11.limitation:
                        pow_difficulty = nip11.limitation.get("min_pow_difficulty", 0)
                        if pow_difficulty and pow_difficulty > 0:
                            event_builder = event_builder.pow(pow_difficulty)

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
                    nip66_meta = nip66.to_relay_metadata()

                result = CheckResult(
                    nip11=nip11.to_relay_metadata() if nip11 else None,
                    rtt=nip66_meta.rtt if nip66_meta else None,
                    probe=nip66_meta.probe if nip66_meta else None,
                    ssl=nip66_meta.ssl if nip66_meta else None,
                    geo=nip66_meta.geo if nip66_meta else None,
                    net=nip66_meta.net if nip66_meta else None,
                    dns=nip66_meta.dns if nip66_meta else None,
                    http=nip66_meta.http if nip66_meta else None,
                )

                # Log result
                if any(result):
                    self._logger.debug("check_succeeded", url=relay.url)
                else:
                    self._logger.debug("check_failed", url=relay.url)

                return result

            except Exception as e:
                self._logger.debug("check_error", url=relay.url, error=str(e))
                return empty

    # -------------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------------

    async def _persist_results(
        self,
        successful: list[tuple[Relay, CheckResult]],
        failed: list[Relay],
    ) -> None:
        """Persist check results to the database.

        For successful checks:
            - Filters metadata by store config
            - Inserts metadata records using content-addressed deduplication
            - Saves checkpoint with current timestamp

        For failed checks:
            - Updates checkpoint to mark the attempt (prevents immediate retry)
        """
        now = int(time.time())
        store = self._config.processing.store

        # Insert metadata for successful checks (filtered by store config)
        if successful:
            metadata: list[RelayMetadata] = []
            for _, result in successful:
                if result.nip11 and store.nip11:
                    metadata.append(result.nip11)
                if result.rtt and store.nip66_rtt:
                    metadata.append(result.rtt)
                if result.probe and store.nip66_probe:
                    metadata.append(result.probe)
                if result.ssl and store.nip66_ssl:
                    metadata.append(result.ssl)
                if result.geo and store.nip66_geo:
                    metadata.append(result.geo)
                if result.net and store.nip66_net:
                    metadata.append(result.net)
                if result.dns and store.nip66_dns:
                    metadata.append(result.dns)
                if result.http and store.nip66_http:
                    metadata.append(result.http)
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

    async def _broadcast_events(self, builders: list[EventBuilder], relays: list[Relay]) -> None:
        """Broadcast multiple events to the specified relays.

        Connects once and sends all events, then disconnects. More efficient
        than publishing events individually when sending multiple events to
        the same set of relays.

        Args:
            builders: List of event builders to sign and send.
            relays: Target relays to broadcast to.
        """
        if not builders or not relays:
            return

        client = create_client(self._keys)
        for relay in relays:
            await client.add_relay(RelayUrl.parse(relay.url))
        try:
            await client.connect()
            for builder in builders:
                await client.send_event_builder(builder)
        finally:
            await client.shutdown()

    def _get_discovery_relays(self) -> list[Relay]:
        """Get relays for Kind 30166 discovery events (falls back to publishing.relays)."""
        return self._config.discovery.relays or self._config.publishing.relays

    def _get_announcement_relays(self) -> list[Relay]:
        """Get relays for Kind 10166 announcements (falls back to publishing.relays)."""
        return self._config.announcement.relays or self._config.publishing.relays

    def _get_profile_relays(self) -> list[Relay]:
        """Get relays for Kind 0 profile (falls back to publishing.relays)."""
        return self._config.profile.relays or self._config.publishing.relays

    async def _publish_announcement(self) -> None:
        """Publish Kind 10166 announcement if due.

        Rate-limited to once per interval. Timestamp persisted in service_data.
        """
        ann = self._config.announcement
        relays = self._get_announcement_relays()
        if not ann.enabled or not relays or self._keys is None:
            return

        last_announcement = await self._get_cursor_timestamp("last_announcement")
        elapsed = time.time() - last_announcement
        if elapsed < ann.interval:
            return

        try:
            builder = self._build_kind_10166()
            await self._broadcast_events([builder], relays)
            self._logger.info("announcement_published", relays=len(relays))
            await self._set_cursor_timestamp("last_announcement", time.time())
        except Exception as e:
            self._logger.warning("announcement_failed", error=str(e))

    async def _publish_profile(self) -> None:
        """Publish Kind 0 profile if due.

        Rate-limited to once per interval. Timestamp persisted in service_data.
        """
        profile = self._config.profile
        relays = self._get_profile_relays()
        if not profile.enabled or not relays or self._keys is None:
            return

        last_profile = await self._get_cursor_timestamp("last_profile")
        elapsed = time.time() - last_profile
        if elapsed < profile.interval:
            return

        try:
            builder = self._build_kind_0()
            await self._broadcast_events([builder], relays)
            self._logger.info("profile_published", relays=len(relays))
            await self._set_cursor_timestamp("last_profile", time.time())
        except Exception as e:
            self._logger.warning("profile_failed", error=str(e))

    async def _publish_relay_discoveries(self, successful: list[tuple[Relay, CheckResult]]) -> None:
        """Publish Kind 30166 relay discovery events for all successful checks.

        Builds all events first, then broadcasts them in a single connection
        for efficiency.

        Args:
            successful: List of (relay, result) tuples from successful checks.
        """
        disc = self._config.discovery
        relays = self._get_discovery_relays()
        if not disc.enabled or not relays or self._keys is None:
            return

        builders: list[EventBuilder] = []
        for relay, result in successful:
            try:
                builders.append(self._build_kind_30166(relay, result))
            except Exception as e:
                self._logger.debug("build_30166_failed", url=relay.url, error=str(e))

        if builders:
            try:
                await self._broadcast_events(builders, relays)
                self._logger.debug("discoveries_published", count=len(builders))
            except Exception as e:
                self._logger.warning(
                    "discoveries_broadcast_failed", count=len(builders), error=str(e)
                )

    # -------------------------------------------------------------------------
    # Event Builders
    # -------------------------------------------------------------------------

    def _build_kind_0(self) -> EventBuilder:
        """Build Kind 0 profile metadata event per NIP-01.

        Creates a replaceable event with the monitor's profile information
        including name, about, picture, nip05, website, banner, and lud16.
        Only non-empty fields from profile config are included.

        Returns:
            EventBuilder ready for signing and publishing.
        """
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
        """Build Kind 10166 monitor announcement event per NIP-66.

        Creates a replaceable event announcing this monitor's capabilities.
        Tags include:
            - frequency: How often checks run (seconds)
            - timeout: Timeout per check type (open, read, write, nip11, ssl)
            - c: Check types performed (open, read, write, nip11, ssl, geo, net)

        Returns:
            EventBuilder ready for signing and publishing.
        """
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

    def _build_kind_30166(self, relay: Relay, result: CheckResult) -> EventBuilder:
        """Build Kind 30166 relay discovery event per NIP-66.

        Creates an addressable event (d-tag = relay URL) with health check results.
        Content is the NIP-11 JSON if available. Tags include:

        Required:
            - d: Relay URL (addressable identifier)
            - n: Network type (clearnet, tor, i2p, lokinet)

        From NIP-66 checks (if enabled and data available):
            - rtt-open/read/write: Round-trip times in milliseconds
            - ssl, ssl-expires, ssl-issuer: Certificate validation
            - net-ip, net-ipv6, net-asn, net-asn-org: Network info
            - g, geo-country, geo-city, geo-lat, geo-lon, geo-tz: Geolocation

        From NIP-11 (if enabled and relay provides it):
            - N: Supported NIP numbers
            - t: Topic tags from relay
            - l: Language codes (ISO-639-1)
            - R: Requirements (auth, payment, writes, pow with ! prefix if not required)
            - T: Relay types (Search, Community, Blob, Paid, PrivateStorage,
                 PrivateInbox, PublicOutbox, PublicInbox)

        R and T tags combine NIP-11 claims with probe verification - probe results
        override self-reported capabilities when they conflict.

        Args:
            relay: The relay being described.
            result: Health check results containing metadata.

        Returns:
            EventBuilder ready for signing and publishing.
        """
        include = self._config.discovery.include
        content = result.nip11.metadata.to_db_params()[0] if result.nip11 else ""
        tags = [
            Tag.parse(["d", relay.url]),
            Tag.parse(["n", relay.network.value]),
        ]

        # NIP-66 RTT tags
        if result.rtt and include.nip66_rtt:
            rtt_data = result.rtt.metadata.data
            if rtt_data.get("rtt_open") is not None:
                tags.append(Tag.parse(["rtt-open", str(rtt_data["rtt_open"])]))
            if rtt_data.get("rtt_read") is not None:
                tags.append(Tag.parse(["rtt-read", str(rtt_data["rtt_read"])]))
            if rtt_data.get("rtt_write") is not None:
                tags.append(Tag.parse(["rtt-write", str(rtt_data["rtt_write"])]))

        # NIP-66 SSL tags
        if result.ssl and include.nip66_ssl:
            ssl_data = result.ssl.metadata.data
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
        if result.net and include.nip66_net:
            net_data = result.net.metadata.data
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
        if result.geo and include.nip66_geo:
            geo_data = result.geo.metadata.data
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

        # NIP-11 capability tags (self-reported by relay)
        if result.nip11 and include.nip11:
            nip11_data = result.nip11.metadata.data

            # N tags: supported NIPs
            supported_nips = nip11_data.get("supported_nips")
            if supported_nips:
                for nip in supported_nips:
                    tags.append(Tag.parse(["N", str(nip)]))

            # t tags: topic tags
            nip11_tags = nip11_data.get("tags")
            if nip11_tags:
                for topic in nip11_tags:
                    tags.append(Tag.parse(["t", topic]))

            # l tags: language tags (ISO-639-1)
            # NIP-11 uses IETF tags (e.g., "en-419"), extract primary subtag for ISO-639-1
            # "*" means global relay (all languages) - skip l tags in that case
            language_tags = nip11_data.get("language_tags")
            if language_tags and "*" not in language_tags:
                seen_langs: set[str] = set()
                for lang in language_tags:
                    # Extract primary language subtag (before hyphen) for ISO-639-1
                    # e.g., "en-419" -> "en", "pt-BR" -> "pt"
                    primary = lang.split("-")[0].lower() if lang else ""
                    if primary and len(primary) == 2 and primary not in seen_langs:
                        seen_langs.add(primary)
                        tags.append(Tag.parse(["l", primary, "ISO-639-1"]))

            # Combine NIP-11 claims with probe verification
            limitation = nip11_data.get("limitation") or {}
            nip11_auth = limitation.get("auth_required", False)
            nip11_payment = limitation.get("payment_required", False)
            nip11_writes = limitation.get("restricted_writes", False)
            pow_diff = limitation.get("min_pow_difficulty", 0)

            # Get probe results for verification (probe overrides NIP-11 claims)
            probe_data = result.probe.metadata.data if result.probe else {}
            write_success = probe_data.get("probe_write_success")
            write_reason = (probe_data.get("probe_write_reason") or "").lower()
            read_success = probe_data.get("probe_read_success")
            read_reason = (probe_data.get("probe_read_reason") or "").lower()

            # Determine actual restrictions from probe results
            # Probe results override NIP-11 claims when available
            if write_success is False and write_reason:
                # Probe detected actual restrictions
                probe_auth = "auth" in write_reason
                probe_payment = "pay" in write_reason or "paid" in write_reason
                probe_writes = not probe_auth and not probe_payment  # generic rejection
            else:
                probe_auth = False
                probe_payment = False
                probe_writes = False

            # Final determination: NIP-11 OR probe detected
            auth = nip11_auth or probe_auth
            payment = nip11_payment or probe_payment
            # restricted_writes: NIP-11 says restricted, OR probe failed without auth/payment
            # BUT if probe succeeded, writes are actually open (False overrides)
            writes = False if write_success is True else nip11_writes or probe_writes

            # Check if read requires auth (from probe)
            read_auth = read_success is False and "auth" in read_reason

            # R tags
            tags.append(Tag.parse(["R", "auth" if auth else "!auth"]))
            tags.append(Tag.parse(["R", "payment" if payment else "!payment"]))
            tags.append(Tag.parse(["R", "writes" if writes else "!writes"]))
            tags.append(Tag.parse(["R", "pow" if pow_diff and pow_diff > 0 else "!pow"]))

            # T tags: relay types (per issue #1282)
            # A relay can have multiple types, so we emit all applicable T tags
            nips = set(supported_nips) if supported_nips else set()

            # Capability-based types (from supported_nips)
            if 50 in nips:
                tags.append(Tag.parse(["T", "Search"]))
            if 29 in nips:
                tags.append(Tag.parse(["T", "Community"]))
            if 95 in nips:
                tags.append(Tag.parse(["T", "Blob"]))

            # Access-based types (from limitation + probe verification)
            # Payment is a modifier - emitted separately, but also implies write restriction
            if payment:
                tags.append(Tag.parse(["T", "Paid"]))

            # Determine primary access type based on read/write restrictions
            if read_auth:
                if auth:
                    # Both read and write require auth = PrivateStorage
                    tags.append(Tag.parse(["T", "PrivateStorage"]))
                else:
                    # Only read requires auth (p-tagged can download, anyone uploads)
                    tags.append(Tag.parse(["T", "PrivateInbox"]))
            elif auth or writes or payment:
                # Read is open, writes restricted (by auth, whitelist, or payment)
                tags.append(Tag.parse(["T", "PublicOutbox"]))
            else:
                # Both read and write are completely open
                tags.append(Tag.parse(["T", "PublicInbox"]))

        return EventBuilder(Kind(30166), content).tags(tags)
