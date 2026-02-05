"""Monitor service for relay health monitoring with NIP-66 compliance.

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

Usage:
    from core import Brotr
    from services import Monitor

    brotr = Brotr.from_yaml("yaml/core/brotr.yaml")
    monitor = Monitor.from_yaml("yaml/services/monitor.yaml", brotr=brotr)

    async with brotr:
        async with monitor:
            await monitor.run_forever()
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import random
import time
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, ClassVar, NamedTuple, TypeVar

import geoip2.database
from nostr_sdk import EventBuilder, Filter, Keys, Kind, RelayUrl, Tag
from pydantic import BaseModel, BeforeValidator, Field, PlainSerializer, model_validator

from core.service import BaseService, BaseServiceConfig, NetworkSemaphoreMixin
from models import Metadata, MetadataType, Nip11, Relay, RelayMetadata
from models.nips.base import BaseMetadata
from models.nips.nip66 import (
    Nip66DnsMetadata,
    Nip66GeoMetadata,
    Nip66HttpMetadata,
    Nip66NetMetadata,
    Nip66RttMetadata,
    Nip66SslMetadata,
)
from utils.keys import KeysConfig
from utils.network import NetworkConfig, NetworkType
from utils.progress import BatchProgress
from utils.transport import create_client


if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from core.brotr import Brotr


# =============================================================================
# Constants
# =============================================================================

# ISO 639-1 language code length
_ISO_639_1_LENGTH = 2

# NIP numbers for capability-based type tags
_NIP_SEARCH = 50  # NIP-50 search
_NIP_COMMUNITY = 29  # NIP-29 communities
_NIP_BLOSSOM = 95  # NIP-95 blob storage


# =============================================================================
# Type Aliases and Helpers
# =============================================================================

_T = TypeVar("_T")


def _parse_relays(v: list[str | Relay]) -> list[Relay]:
    """Parse relay URL strings into Relay objects, skipping invalid URLs."""
    relays: list[Relay] = []
    for x in v:
        if isinstance(x, Relay):
            relays.append(x)
        else:
            with contextlib.suppress(ValueError):
                relays.append(Relay(x))
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
# Result Types
# =============================================================================


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


# =============================================================================
# Configuration Classes
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


class RetryConfig(BaseModel):
    """Retry settings with exponential backoff for a single metadata operation."""

    max_retries: int = Field(default=0, ge=0, le=10)
    base_delay: float = Field(default=1.0, ge=0.1, le=10.0)
    max_delay: float = Field(default=10.0, ge=1.0, le=60.0)
    jitter: float = Field(default=0.5, ge=0.0, le=2.0)


class MetadataRetryConfig(BaseModel):
    """Retry settings for each metadata type."""

    nip11: RetryConfig = Field(default_factory=RetryConfig)
    nip66_rtt: RetryConfig = Field(default_factory=RetryConfig)
    nip66_ssl: RetryConfig = Field(default_factory=RetryConfig)
    nip66_geo: RetryConfig = Field(default_factory=RetryConfig)
    nip66_net: RetryConfig = Field(default_factory=RetryConfig)
    nip66_dns: RetryConfig = Field(default_factory=RetryConfig)
    nip66_http: RetryConfig = Field(default_factory=RetryConfig)


class ProcessingConfig(BaseModel):
    """Processing settings including what to compute and store."""

    chunk_size: int = Field(default=100, ge=10, le=1000)
    max_relays: int | None = Field(default=None, ge=1)
    nip11_max_size: int = Field(default=1_048_576, ge=1024, le=10_485_760)
    retry: MetadataRetryConfig = Field(default_factory=MetadataRetryConfig)
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


class Monitor(NetworkSemaphoreMixin, BaseService[MonitorConfig]):
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
    # Main Cycle
    # -------------------------------------------------------------------------

    async def run(self) -> None:
        """Execute one complete monitoring cycle."""
        self._progress.reset()
        self._init_semaphores(self._config.networks)

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
        """Update GeoLite2 databases if stale based on max_age_days."""
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
        """Open GeoIP database readers for the current run."""
        if self._config.processing.compute.nip66_geo:
            self._geo_reader = geoip2.database.Reader(self._config.geo.city_database_path)

        if self._config.processing.compute.nip66_net:
            self._asn_reader = geoip2.database.Reader(self._config.geo.asn_database_path)

    def _close_geo_readers(self) -> None:
        """Close GeoIP database readers after the run."""
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
        """Emit Prometheus metrics reflecting current cycle state."""
        self.set_gauge("total", self._progress.total)
        self.set_gauge("processed", self._progress.processed)
        self.set_gauge("success", self._progress.success)
        self.set_gauge("failure", self._progress.failure)

    # -------------------------------------------------------------------------
    # Counting
    # -------------------------------------------------------------------------

    async def _count_relays(self, networks: list[str]) -> int:
        """Count the total number of relays needing checks for enabled networks."""
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
        """Process all pending relays in configurable chunks."""
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
        """Fetch the next chunk of relays for health checking."""
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
        """Check a chunk of relays concurrently."""
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

    @staticmethod
    def _get_success(result: Any) -> bool:
        """Extract success status from metadata logs."""
        logs = result.logs
        if hasattr(logs, "success"):
            return bool(logs.success)
        if hasattr(logs, "open_success"):
            return bool(logs.open_success)
        return False

    @staticmethod
    def _get_reason(result: Any) -> str | None:
        """Extract failure reason from metadata logs."""
        logs = result.logs
        if hasattr(logs, "reason"):
            return str(logs.reason) if logs.reason else None
        if hasattr(logs, "open_reason"):
            return str(logs.open_reason) if logs.open_reason else None
        return None

    async def _with_retry(
        self,
        coro_factory: Callable[[], Coroutine[Any, Any, _T]],
        retry_config: RetryConfig,
        operation: str,
        relay_url: str,
    ) -> _T | None:
        """Execute metadata fetch with exponential backoff retry."""
        max_retries = retry_config.max_retries
        result = None

        for attempt in range(max_retries + 1):
            try:
                result = await coro_factory()
                if self._get_success(result):
                    return result
            except Exception as e:
                self._logger.debug(
                    f"{operation}_error",
                    relay=relay_url,
                    attempt=attempt + 1,
                    error=str(e),
                )
                return None

            # Network failure - retry if attempts remaining
            if attempt < max_retries:
                delay = min(retry_config.base_delay * (2**attempt), retry_config.max_delay)
                jitter = random.uniform(0, retry_config.jitter)
                await asyncio.sleep(delay + jitter)
                self._logger.debug(
                    f"{operation}_retry",
                    relay=relay_url,
                    attempt=attempt + 1,
                    reason=self._get_reason(result) if result else None,
                    delay_s=round(delay + jitter, 2),
                )

        # All retries exhausted
        self._logger.debug(
            f"{operation}_failed",
            relay=relay_url,
            attempts=max_retries + 1,
            reason=self._get_reason(result) if result else None,
        )
        return result

    async def _check_one(self, relay: Relay) -> CheckResult:
        """Perform health checks on a single relay."""
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
            generated_at = int(time.time())

            # Helper to convert metadata to RelayMetadata
            def to_relay_meta(
                meta: BaseMetadata | None, meta_type: MetadataType
            ) -> RelayMetadata | None:
                if meta is None:
                    return None
                return RelayMetadata(
                    relay=relay,
                    metadata=Metadata(type=meta_type, value=meta.to_dict()),
                    generated_at=generated_at,
                )

            try:
                # NIP-11 check (with retry)
                if compute.nip11:
                    nip11 = await self._with_retry(
                        lambda: Nip11.create(
                            relay,
                            timeout=timeout,
                            max_size=self._config.processing.nip11_max_size,
                            proxy_url=proxy_url,
                        ),
                        self._config.processing.retry.nip11,
                        "nip11",
                        relay.url,
                    )

                # NIP-66 individual tests
                rtt_meta: Nip66RttMetadata | None = None
                ssl_meta: Nip66SslMetadata | None = None
                dns_meta: Nip66DnsMetadata | None = None
                geo_meta: Nip66GeoMetadata | None = None
                net_meta: Nip66NetMetadata | None = None
                http_meta: Nip66HttpMetadata | None = None

                # RTT test (requires keys, event_builder, read_filter)
                if compute.nip66_rtt:
                    event_builder = EventBuilder(Kind(30000), "nip66-test").tags(
                        [Tag.parse(["d", relay.url])]
                    )
                    # Add POW if NIP-11 specifies minimum difficulty
                    if nip11 and nip11.fetch_metadata and nip11.fetch_metadata.logs.success:
                        pow_difficulty = nip11.fetch_metadata.data.limitation.min_pow_difficulty
                        if pow_difficulty and pow_difficulty > 0:
                            event_builder = event_builder.pow(pow_difficulty)
                    read_filter = Filter().limit(1)
                    rtt_meta = await self._with_retry(
                        lambda: Nip66RttMetadata.rtt(
                            relay, self._keys, event_builder, read_filter, timeout, proxy_url
                        ),
                        self._config.processing.retry.nip66_rtt,
                        "nip66_rtt",
                        relay.url,
                    )

                # SSL test (clearnet only)
                if compute.nip66_ssl and relay.network == NetworkType.CLEARNET:
                    ssl_meta = await self._with_retry(
                        lambda: Nip66SslMetadata.ssl(relay, timeout),
                        self._config.processing.retry.nip66_ssl,
                        "nip66_ssl",
                        relay.url,
                    )

                # DNS test (clearnet only)
                if compute.nip66_dns and relay.network == NetworkType.CLEARNET:
                    dns_meta = await self._with_retry(
                        lambda: Nip66DnsMetadata.dns(relay, timeout),
                        self._config.processing.retry.nip66_dns,
                        "nip66_dns",
                        relay.url,
                    )

                # Geo test (requires city_reader, clearnet only)
                geo_reader = self._geo_reader
                if compute.nip66_geo and geo_reader and relay.network == NetworkType.CLEARNET:
                    geo_meta = await self._with_retry(
                        lambda: Nip66GeoMetadata.geo(relay, geo_reader),
                        self._config.processing.retry.nip66_geo,
                        "nip66_geo",
                        relay.url,
                    )

                # Net test (requires asn_reader, clearnet only)
                asn_reader = self._asn_reader
                if compute.nip66_net and asn_reader and relay.network == NetworkType.CLEARNET:
                    net_meta = await self._with_retry(
                        lambda: Nip66NetMetadata.net(relay, asn_reader),
                        self._config.processing.retry.nip66_net,
                        "nip66_net",
                        relay.url,
                    )

                # HTTP test
                if compute.nip66_http:
                    http_meta = await self._with_retry(
                        lambda: Nip66HttpMetadata.http(relay, timeout, proxy_url),
                        self._config.processing.retry.nip66_http,
                        "nip66_http",
                        relay.url,
                    )

                # Convert NIP-11
                result = CheckResult(
                    nip11=nip11.to_relay_metadata_tuple().nip11_fetch if nip11 else None,
                    rtt=to_relay_meta(rtt_meta, MetadataType.NIP66_RTT),
                    probe=None,
                    ssl=to_relay_meta(ssl_meta, MetadataType.NIP66_SSL),
                    geo=to_relay_meta(geo_meta, MetadataType.NIP66_GEO),
                    net=to_relay_meta(net_meta, MetadataType.NIP66_NET),
                    dns=to_relay_meta(dns_meta, MetadataType.NIP66_DNS),
                    http=to_relay_meta(http_meta, MetadataType.NIP66_HTTP),
                )

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
        """Persist check results to the database."""
        now = int(time.time())
        store = self._config.processing.store

        # Insert metadata for successful checks
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

        # Save checkpoints for all checked relays
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
        """Broadcast multiple events to the specified relays."""
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
        """Get relays for Kind 30166 discovery events."""
        return self._config.discovery.relays or self._config.publishing.relays

    def _get_announcement_relays(self) -> list[Relay]:
        """Get relays for Kind 10166 announcements."""
        return self._config.announcement.relays or self._config.publishing.relays

    def _get_profile_relays(self) -> list[Relay]:
        """Get relays for Kind 0 profile."""
        return self._config.profile.relays or self._config.publishing.relays

    async def _publish_announcement(self) -> None:
        """Publish Kind 10166 announcement if due."""
        ann = self._config.announcement
        relays = self._get_announcement_relays()
        if not ann.enabled or not relays:
            return

        results = await self._brotr.get_service_data(
            self.SERVICE_NAME, "cursor", "last_announcement"
        )
        last_announcement = results[0].get("value", {}).get("timestamp", 0.0) if results else 0.0
        elapsed = time.time() - last_announcement
        if elapsed < ann.interval:
            return

        try:
            builder = self._build_kind_10166()
            await self._broadcast_events([builder], relays)
            self._logger.info("announcement_published", relays=len(relays))
            await self._brotr.upsert_service_data(
                [(self.SERVICE_NAME, "cursor", "last_announcement", {"timestamp": time.time()})]
            )
        except Exception as e:
            self._logger.warning("announcement_failed", error=str(e))

    async def _publish_profile(self) -> None:
        """Publish Kind 0 profile if due."""
        profile = self._config.profile
        relays = self._get_profile_relays()
        if not profile.enabled or not relays:
            return

        results = await self._brotr.get_service_data(self.SERVICE_NAME, "cursor", "last_profile")
        last_profile = results[0].get("value", {}).get("timestamp", 0.0) if results else 0.0
        elapsed = time.time() - last_profile
        if elapsed < profile.interval:
            return

        try:
            builder = self._build_kind_0()
            await self._broadcast_events([builder], relays)
            self._logger.info("profile_published", relays=len(relays))
            await self._brotr.upsert_service_data(
                [(self.SERVICE_NAME, "cursor", "last_profile", {"timestamp": time.time()})]
            )
        except Exception as e:
            self._logger.warning("profile_failed", error=str(e))

    async def _publish_relay_discoveries(self, successful: list[tuple[Relay, CheckResult]]) -> None:
        """Publish Kind 30166 relay discovery events for all successful checks."""
        disc = self._config.discovery
        relays = self._get_discovery_relays()
        if not disc.enabled or not relays:
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
        """Build Kind 0 profile metadata event per NIP-01."""
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
        """Build Kind 10166 monitor announcement event per NIP-66."""
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

    # -------------------------------------------------------------------------
    # Kind 30166 Tag Helpers
    # -------------------------------------------------------------------------

    def _add_rtt_tags(self, tags: list[Tag], result: CheckResult, include: MetadataFlags) -> None:
        """Add RTT-related tags (rtt-open, rtt-read, rtt-write)."""
        if not result.rtt or not include.nip66_rtt:
            return
        rtt_data = result.rtt.metadata.value
        if rtt_data.get("rtt_open") is not None:
            tags.append(Tag.parse(["rtt-open", str(rtt_data["rtt_open"])]))
        if rtt_data.get("rtt_read") is not None:
            tags.append(Tag.parse(["rtt-read", str(rtt_data["rtt_read"])]))
        if rtt_data.get("rtt_write") is not None:
            tags.append(Tag.parse(["rtt-write", str(rtt_data["rtt_write"])]))

    def _add_ssl_tags(self, tags: list[Tag], result: CheckResult, include: MetadataFlags) -> None:
        """Add SSL-related tags (ssl, ssl-expires, ssl-issuer)."""
        if not result.ssl or not include.nip66_ssl:
            return
        ssl_data = result.ssl.metadata.value
        ssl_valid = ssl_data.get("ssl_valid")
        if ssl_valid is not None:
            tags.append(Tag.parse(["ssl", "valid" if ssl_valid else "!valid"]))
        ssl_expires = ssl_data.get("ssl_expires")
        if ssl_expires is not None:
            tags.append(Tag.parse(["ssl-expires", str(ssl_expires)]))
        ssl_issuer = ssl_data.get("ssl_issuer")
        if ssl_issuer:
            tags.append(Tag.parse(["ssl-issuer", ssl_issuer]))

    def _add_net_tags(self, tags: list[Tag], result: CheckResult, include: MetadataFlags) -> None:
        """Add network tags (net-ip, net-ipv6, net-asn, net-asn-org)."""
        if not result.net or not include.nip66_net:
            return
        net_data = result.net.metadata.value
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

    def _add_geo_tags(self, tags: list[Tag], result: CheckResult, include: MetadataFlags) -> None:
        """Add geolocation tags (g, geo-country, geo-city, geo-lat, geo-lon, geo-tz)."""
        if not result.geo or not include.nip66_geo:
            return
        geo_data = result.geo.metadata.value
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

    def _add_nip11_tags(self, tags: list[Tag], result: CheckResult, include: MetadataFlags) -> None:
        """Add NIP-11 capability tags (N, t, l, R, T)."""
        if not result.nip11 or not include.nip11:
            return
        nip11_data = result.nip11.metadata.value

        # N tags: supported NIPs
        supported_nips = nip11_data.get("supported_nips")
        if supported_nips:
            tags.extend(Tag.parse(["N", str(nip)]) for nip in supported_nips)

        # t tags: topic tags
        nip11_tags = nip11_data.get("tags")
        if nip11_tags:
            tags.extend(Tag.parse(["t", topic]) for topic in nip11_tags)

        # l tags: language tags (ISO-639-1)
        self._add_language_tags(tags, nip11_data)

        # R and T tags: requirements and types
        self._add_requirement_and_type_tags(tags, result, nip11_data, supported_nips)

    def _add_language_tags(self, tags: list[Tag], nip11_data: dict[str, Any]) -> None:
        """Add language tags (l) from NIP-11 language_tags."""
        language_tags = nip11_data.get("language_tags")
        if not language_tags or "*" in language_tags:
            return
        seen_langs: set[str] = set()
        for lang in language_tags:
            primary = lang.split("-")[0].lower() if lang else ""
            if primary and len(primary) == _ISO_639_1_LENGTH and primary not in seen_langs:
                seen_langs.add(primary)
                tags.append(Tag.parse(["l", primary, "ISO-639-1"]))

    def _add_requirement_and_type_tags(
        self,
        tags: list[Tag],
        result: CheckResult,
        nip11_data: dict[str, Any],
        supported_nips: list[int] | None,
    ) -> None:
        """Add R (requirement) and T (type) tags combining NIP-11 with probe results."""
        limitation = nip11_data.get("limitation") or {}
        nip11_auth = limitation.get("auth_required", False)
        nip11_payment = limitation.get("payment_required", False)
        nip11_writes = limitation.get("restricted_writes", False)
        pow_diff = limitation.get("min_pow_difficulty", 0)

        # Get probe results for verification
        probe_data = result.probe.metadata.value if result.probe else {}
        write_success = probe_data.get("probe_write_success")
        write_reason = (probe_data.get("probe_write_reason") or "").lower()
        read_success = probe_data.get("probe_read_success")
        read_reason = (probe_data.get("probe_read_reason") or "").lower()

        # Determine actual restrictions from probe results
        if write_success is False and write_reason:
            probe_auth = "auth" in write_reason
            probe_payment = "pay" in write_reason or "paid" in write_reason
            probe_writes = not probe_auth and not probe_payment
        else:
            probe_auth = False
            probe_payment = False
            probe_writes = False

        # Final determination
        auth = bool(nip11_auth or probe_auth)
        payment = bool(nip11_payment or probe_payment)
        writes = False if write_success is True else bool(nip11_writes or probe_writes)
        read_auth = read_success is False and "auth" in read_reason

        # R tags
        tags.append(Tag.parse(["R", "auth" if auth else "!auth"]))
        tags.append(Tag.parse(["R", "payment" if payment else "!payment"]))
        tags.append(Tag.parse(["R", "writes" if writes else "!writes"]))
        tags.append(Tag.parse(["R", "pow" if pow_diff and pow_diff > 0 else "!pow"]))

        # T tags: relay types
        self._add_type_tags(tags, supported_nips, payment, auth, writes, read_auth)

    def _add_type_tags(
        self,
        tags: list[Tag],
        supported_nips: list[int] | None,
        payment: bool,
        auth: bool,
        writes: bool,
        read_auth: bool,
    ) -> None:
        """Add T (type) tags based on NIPs and access restrictions."""
        nips = set(supported_nips) if supported_nips else set()

        # Capability-based types (from supported_nips)
        if _NIP_SEARCH in nips:
            tags.append(Tag.parse(["T", "Search"]))
        if _NIP_COMMUNITY in nips:
            tags.append(Tag.parse(["T", "Community"]))
        if _NIP_BLOSSOM in nips:
            tags.append(Tag.parse(["T", "Blob"]))

        # Payment modifier
        if payment:
            tags.append(Tag.parse(["T", "Paid"]))

        # Determine primary access type based on read/write restrictions
        if read_auth:
            if auth:
                tags.append(Tag.parse(["T", "PrivateStorage"]))
            else:
                tags.append(Tag.parse(["T", "PrivateInbox"]))
        elif auth or writes or payment:
            tags.append(Tag.parse(["T", "PublicOutbox"]))
        else:
            tags.append(Tag.parse(["T", "PublicInbox"]))

    def _build_kind_30166(self, relay: Relay, result: CheckResult) -> EventBuilder:
        """Build Kind 30166 relay discovery event per NIP-66."""
        include = self._config.discovery.include
        content = result.nip11.metadata.to_db_params().id if result.nip11 else ""
        tags: list[Tag] = [
            Tag.parse(["d", relay.url]),
            Tag.parse(["n", relay.network.value]),
        ]

        # Add NIP-66 metadata tags
        self._add_rtt_tags(tags, result, include)
        self._add_ssl_tags(tags, result, include)
        self._add_net_tags(tags, result, include)
        self._add_geo_tags(tags, result, include)

        # Add NIP-11 capability tags
        self._add_nip11_tags(tags, result, include)

        return EventBuilder(Kind(30166), content).tags(tags)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "AnnouncementConfig",
    "CheckResult",
    "DiscoveryConfig",
    "GeoConfig",
    "MetadataFlags",
    "MetadataRetryConfig",
    "Monitor",
    "MonitorConfig",
    "ProcessingConfig",
    "ProfileConfig",
    "PublishingConfig",
    "RelayList",
    "RetryConfig",
]
