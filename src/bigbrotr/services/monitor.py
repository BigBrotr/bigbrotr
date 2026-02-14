"""Monitor service for relay health monitoring with NIP-66 compliance.

Performs comprehensive health checks on relays and stores results as
content-addressed [Metadata][bigbrotr.models.metadata.Metadata]. Optionally
publishes Kind 30166 relay discovery events and Kind 10166 monitor
announcements to the Nostr network.

Health checks include:

- [Nip11][bigbrotr.nips.nip11.Nip11]: Relay info document (name,
  description, pubkey, supported NIPs).
- [Nip66RttMetadata][bigbrotr.nips.nip66.Nip66RttMetadata]: Open/read/write
  round-trip times in milliseconds.
- [Nip66SslMetadata][bigbrotr.nips.nip66.Nip66SslMetadata]: SSL certificate
  validation (clearnet only).
- [Nip66DnsMetadata][bigbrotr.nips.nip66.Nip66DnsMetadata]: DNS hostname
  resolution (clearnet only).
- [Nip66GeoMetadata][bigbrotr.nips.nip66.Nip66GeoMetadata]: IP geolocation
  (clearnet only).
- [Nip66NetMetadata][bigbrotr.nips.nip66.Nip66NetMetadata]: ASN/organization
  info (clearnet only).
- [Nip66HttpMetadata][bigbrotr.nips.nip66.Nip66HttpMetadata]: HTTP status
  codes and headers.

Note:
    The monitor orchestration is split across three modules for clarity:

    - **monitor.py** (this module): Health check orchestration, config,
      GeoIP management, retry logic, and persistence.
    - [monitor_publisher][bigbrotr.services.monitor_publisher]: Nostr event
      signing, broadcasting, and Kind 0/10166/30166 builders.
    - [monitor_tags][bigbrotr.services.monitor_tags]: NIP-66 tag
      construction for Kind 30166 events.

See Also:
    [MonitorConfig][bigbrotr.services.monitor.MonitorConfig]: Configuration
        model for networks, processing, geo, publishing, and discovery.
    [BaseService][bigbrotr.core.base_service.BaseService]: Abstract base
        class providing ``run()``, ``run_forever()``, and ``from_yaml()``.
    [Brotr][bigbrotr.core.brotr.Brotr]: Database facade used for metadata
        persistence and checkpoint management.
    [Validator][bigbrotr.services.validator.Validator]: Upstream service
        that promotes candidates to the ``relay`` table.
    [MonitorPublisherMixin][bigbrotr.services.monitor_publisher.MonitorPublisherMixin]:
        Publishing logic mixed into the Monitor class.
    [MonitorTagsMixin][bigbrotr.services.monitor_tags.MonitorTagsMixin]:
        Tag-building logic mixed into the Monitor class.

Examples:
    ```python
    from bigbrotr.core import Brotr
    from bigbrotr.services import Monitor

    brotr = Brotr.from_yaml("config/brotr.yaml")
    monitor = Monitor.from_yaml("config/services/monitor.yaml", brotr=brotr)

    async with brotr:
        async with monitor:
            await monitor.run_forever()
    ```
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import shutil
import time
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, ClassVar, NamedTuple, TypeVar

import asyncpg
import geoip2.database
from nostr_sdk import EventBuilder, Filter, Keys, Kind, Tag
from pydantic import BaseModel, BeforeValidator, Field, PlainSerializer, model_validator

from bigbrotr.core.base_service import BaseService, BaseServiceConfig
from bigbrotr.models import Metadata, MetadataType, Relay, RelayMetadata
from bigbrotr.models.constants import EventKind, NetworkType, ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.nips.base import BaseNipMetadata  # noqa: TC001
from bigbrotr.nips.nip11 import Nip11, Nip11Options
from bigbrotr.nips.nip66 import (
    Nip66DnsMetadata,
    Nip66GeoMetadata,
    Nip66HttpMetadata,
    Nip66NetMetadata,
    Nip66RttDependencies,
    Nip66RttMetadata,
    Nip66SslMetadata,
)
from bigbrotr.utils.keys import KeysConfig

from .common.configs import NetworkConfig
from .common.mixins import BatchProgressMixin, NetworkSemaphoreMixin
from .common.queries import count_relays_due_for_check, fetch_relays_due_for_check
from .monitor_publisher import MonitorPublisherMixin
from .monitor_tags import MonitorTagsMixin


if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from bigbrotr.core.brotr import Brotr


# =============================================================================
# Constants
# =============================================================================

_SECONDS_PER_DAY = 86_400


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


def _download_geolite_db(url: str, dest: Path, timeout: float = 60.0) -> None:
    """Download a GeoLite2 database file from GitHub mirror.

    Args:
        url: Download URL for the .mmdb file.
        dest: Local path to save the database.
        timeout: Socket timeout in seconds for the HTTP request.

    Raises:
        urllib.error.URLError: If download fails or times out.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url)  # noqa: S310
    with urllib.request.urlopen(request, timeout=timeout) as response, dest.open("wb") as out:  # noqa: S310
        shutil.copyfileobj(response, out)


# =============================================================================
# Result Types
# =============================================================================


class CheckResult(NamedTuple):
    """Result of a single relay health check.

    Each field contains [RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata]
    if that check was run and produced data, or ``None`` if the check was
    skipped (disabled in config) or failed completely. A relay is considered
    successful if ``any(result)`` is ``True``.

    NIP-66 fields use the ``nip66_`` prefix for disambiguation since this
    container mixes NIP-11 and NIP-66 results.

    Attributes:
        nip11: NIP-11 relay information document (name, description, pubkey, etc.).
        nip66_rtt: Round-trip times for open/read/write operations in milliseconds.
        nip66_ssl: SSL certificate validation (valid, expiry timestamp, issuer).
        nip66_geo: Geolocation data (country, city, coordinates, timezone, geohash).
        nip66_net: Network information (IP address, ASN, organization).
        nip66_dns: DNS resolution data (IPs, CNAME, nameservers, reverse DNS).
        nip66_http: HTTP metadata (status code, headers, redirect chain).

    See Also:
        [MetadataFlags][bigbrotr.services.monitor.MetadataFlags]: Boolean
            flags controlling which check types are computed and stored.
        [MonitorTagsMixin][bigbrotr.services.monitor_tags.MonitorTagsMixin]:
            Reads these fields to build Kind 30166 tags.
        [MonitorPublisherMixin][bigbrotr.services.monitor_publisher.MonitorPublisherMixin]:
            Publishes discovery events from these results.
    """

    nip11: RelayMetadata | None
    nip66_rtt: RelayMetadata | None
    nip66_ssl: RelayMetadata | None
    nip66_geo: RelayMetadata | None
    nip66_net: RelayMetadata | None
    nip66_dns: RelayMetadata | None
    nip66_http: RelayMetadata | None


# =============================================================================
# Configuration Classes
# =============================================================================


class MetadataFlags(BaseModel):
    """Boolean flags controlling which metadata types to compute, store, or publish.

    Used in three contexts within
    [MonitorProcessingConfig][bigbrotr.services.monitor.MonitorProcessingConfig]:
    ``compute`` (which checks to run), ``store`` (which results to persist),
    and ``discovery.include`` (which results to publish as NIP-66 tags).

    See Also:
        ``MonitorConfig.validate_store_requires_compute``: Validator
            ensuring stored flags are a subset of computed flags.
    """

    nip11_info: bool = Field(default=True)
    nip66_rtt: bool = Field(default=True)
    nip66_ssl: bool = Field(default=True)
    nip66_geo: bool = Field(default=True)
    nip66_net: bool = Field(default=True)
    nip66_dns: bool = Field(default=True)
    nip66_http: bool = Field(default=True)

    def get_missing_from(self, superset: MetadataFlags) -> list[str]:
        """Return field names that are enabled in self but disabled in superset."""
        return [
            field
            for field in MetadataFlags.model_fields
            if getattr(self, field) and not getattr(superset, field)
        ]


class MonitorRetryConfig(BaseModel):
    """Retry settings with exponential backoff and jitter for metadata operations.

    Warning:
        The ``jitter`` parameter uses ``random.uniform()`` (PRNG, not
        crypto-safe) which is intentional -- jitter only needs to
        decorrelate concurrent retries, not provide cryptographic
        randomness.

    See Also:
        ``Monitor._with_retry``:
            The method that consumes these settings.
    """

    max_attempts: int = Field(default=0, ge=0, le=10)
    initial_delay: float = Field(default=1.0, ge=0.1, le=10.0)
    max_delay: float = Field(default=10.0, ge=1.0, le=60.0)
    jitter: float = Field(default=0.5, ge=0.0, le=2.0)


class MetadataRetryConfig(BaseModel):
    """Per-metadata-type retry settings.

    Each field corresponds to one of the seven health check types and
    holds a [MonitorRetryConfig][bigbrotr.services.monitor.MonitorRetryConfig]
    with independent ``max_attempts``, ``initial_delay``, ``max_delay``,
    and ``jitter`` values.

    See Also:
        [MonitorProcessingConfig][bigbrotr.services.monitor.MonitorProcessingConfig]:
            Parent config that embeds this model.
    """

    nip11_info: MonitorRetryConfig = Field(default_factory=MonitorRetryConfig)
    nip66_rtt: MonitorRetryConfig = Field(default_factory=MonitorRetryConfig)
    nip66_ssl: MonitorRetryConfig = Field(default_factory=MonitorRetryConfig)
    nip66_geo: MonitorRetryConfig = Field(default_factory=MonitorRetryConfig)
    nip66_net: MonitorRetryConfig = Field(default_factory=MonitorRetryConfig)
    nip66_dns: MonitorRetryConfig = Field(default_factory=MonitorRetryConfig)
    nip66_http: MonitorRetryConfig = Field(default_factory=MonitorRetryConfig)


class MonitorProcessingConfig(BaseModel):
    """Processing settings: chunk size, retry policies, and compute/store flags.

    See Also:
        [MonitorConfig][bigbrotr.services.monitor.MonitorConfig]: Parent
            config that embeds this model.
        [MetadataFlags][bigbrotr.services.monitor.MetadataFlags]: The
            ``compute`` and ``store`` flag sets.
    """

    chunk_size: int = Field(default=100, ge=10, le=1000)
    max_relays: int | None = Field(default=None, ge=1)
    allow_insecure: bool = Field(default=False)
    nip11_max_size: int = Field(default=1_048_576, ge=1024, le=10_485_760)
    geohash_precision: int = Field(
        default=9, ge=1, le=12, description="Geohash precision (9=~4.77m)"
    )
    retry: MetadataRetryConfig = Field(default_factory=MetadataRetryConfig)
    compute: MetadataFlags = Field(default_factory=MetadataFlags)
    store: MetadataFlags = Field(default_factory=MetadataFlags)


class GeoConfig(BaseModel):
    """GeoLite2 database paths, download URLs, and staleness settings.

    Note:
        GeoLite2 databases are downloaded at the start of each cycle if
        missing or stale (older than ``max_age_days``). Downloads are
        offloaded to a thread via ``asyncio.to_thread()`` to avoid
        blocking the event loop during large file transfers (10-50 MB).

    See Also:
        [MonitorConfig][bigbrotr.services.monitor.MonitorConfig]: Parent
            config that embeds this model.
        [Nip66GeoMetadata][bigbrotr.nips.nip66.Nip66GeoMetadata]: The
            NIP-66 check that reads the City database.
        [Nip66NetMetadata][bigbrotr.nips.nip66.Nip66NetMetadata]: The
            NIP-66 check that reads the ASN database.
    """

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
    """Default relay list used as fallback for event publishing.

    See Also:
        [DiscoveryConfig][bigbrotr.services.monitor.DiscoveryConfig],
        [AnnouncementConfig][bigbrotr.services.monitor.AnnouncementConfig],
        [ProfileConfig][bigbrotr.services.monitor.ProfileConfig]: Each
            can override this list with their own ``relays`` field.
    """

    relays: RelayList = Field(default_factory=list)


class DiscoveryConfig(BaseModel):
    """Kind 30166 relay discovery event settings (NIP-66).

    See Also:
        ``MonitorTagsMixin._build_kind_30166()``: Builds the event
            from check results using ``include`` flags.
        ``MonitorPublisherMixin._publish_relay_discoveries()``:
            Broadcasts the built events to the configured relays.
    """

    enabled: bool = Field(default=True)
    interval: int = Field(default=3600, ge=60)
    include: MetadataFlags = Field(default_factory=MetadataFlags)
    relays: RelayList = Field(default_factory=list)  # Overrides publishing.relays


class AnnouncementConfig(BaseModel):
    """Kind 10166 monitor announcement settings (NIP-66).

    See Also:
        ``MonitorPublisherMixin._build_kind_10166()``: Builds the
            announcement event with frequency and timeout tags.
    """

    enabled: bool = Field(default=True)
    interval: int = Field(default=86_400, ge=60)
    relays: RelayList = Field(default_factory=list)


class ProfileConfig(BaseModel):
    """Kind 0 profile metadata settings (NIP-01).

    See Also:
        ``MonitorPublisherMixin._build_kind_0()``: Builds the profile
            event from these fields.
    """

    enabled: bool = Field(default=False)
    interval: int = Field(default=86_400, ge=60)
    relays: RelayList = Field(default_factory=list)
    name: str | None = Field(default=None)
    about: str | None = Field(default=None)
    picture: str | None = Field(default=None)
    nip05: str | None = Field(default=None)
    website: str | None = Field(default=None)
    banner: str | None = Field(default=None)
    lud16: str | None = Field(default=None)


class MonitorConfig(BaseServiceConfig):
    """Monitor service configuration with validation for dependency constraints.

    Note:
        Three ``model_validator`` methods enforce dependency constraints
        at config load time (fail-fast):

        - ``validate_geo_databases``: GeoLite2 files must be downloadable.
        - ``validate_store_requires_compute``: Cannot store uncalculated
          metadata.
        - ``validate_publish_requires_compute``: Cannot publish uncalculated
          metadata.

    See Also:
        [Monitor][bigbrotr.services.monitor.Monitor]: The service class
            that consumes this configuration.
        [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
            Base class providing ``interval`` and ``log_level`` fields.
        [KeysConfig][bigbrotr.utils.keys.KeysConfig]: Nostr key
            management for event signing.
    """

    networks: NetworkConfig = Field(default_factory=NetworkConfig)
    keys: KeysConfig = Field(default_factory=lambda: KeysConfig.model_validate({}))
    processing: MonitorProcessingConfig = Field(default_factory=MonitorProcessingConfig)
    geo: GeoConfig = Field(default_factory=GeoConfig)
    publishing: PublishingConfig = Field(default_factory=PublishingConfig)
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    announcement: AnnouncementConfig = Field(default_factory=AnnouncementConfig)
    profile: ProfileConfig = Field(default_factory=ProfileConfig)

    @model_validator(mode="after")
    def validate_geo_databases(self) -> MonitorConfig:
        """Validate GeoLite2 database paths have download URLs if files are missing.

        Actual downloads are deferred to ``_update_geo_databases()`` which runs
        asynchronously via ``asyncio.to_thread()`` to avoid blocking the event loop.
        """
        if self.processing.compute.nip66_geo:
            city_path = Path(self.geo.city_database_path)
            if not city_path.exists() and not self.geo.city_download_url:
                raise ValueError(
                    f"GeoLite2 City database not found at {city_path} "
                    "and no download URL configured in geo.city_download_url"
                )

        if self.processing.compute.nip66_net:
            asn_path = Path(self.geo.asn_database_path)
            if not asn_path.exists() and not self.geo.asn_download_url:
                raise ValueError(
                    f"GeoLite2 ASN database not found at {asn_path} "
                    "and no download URL configured in geo.asn_download_url"
                )

        return self

    @model_validator(mode="after")
    def validate_store_requires_compute(self) -> MonitorConfig:
        """Ensure every stored metadata type is also computed."""
        errors = self.processing.store.get_missing_from(self.processing.compute)
        if errors:
            raise ValueError(
                f"Cannot store metadata that is not computed: {', '.join(errors)}. "
                "Enable in processing.compute.* or disable in processing.store.*"
            )
        return self

    @model_validator(mode="after")
    def validate_publish_requires_compute(self) -> MonitorConfig:
        """Ensure every published metadata type is also computed."""
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


class Monitor(
    MonitorTagsMixin,
    MonitorPublisherMixin,
    BatchProgressMixin,
    NetworkSemaphoreMixin,
    BaseService[MonitorConfig],
):
    """Relay health monitoring service with NIP-66 compliance.

    Performs comprehensive health checks on relays and stores results as
    content-addressed [Metadata][bigbrotr.models.metadata.Metadata].
    Optionally publishes NIP-66 events:

    - **Kind 10166**: Monitor announcement (capabilities, frequency, timeouts).
    - **Kind 30166**: Per-relay discovery event (RTT, SSL, geo, NIP-11 tags).

    Each cycle updates GeoLite2 databases, publishes profile/announcement
    events if due, fetches relays needing checks, processes them in chunks
    with per-network semaphores, persists metadata results, and publishes
    Kind 30166 discovery events. Supports clearnet (direct), Tor, I2P,
    and Lokinet (via SOCKS5 proxy).

    Note:
        The MRO composes four mixins:

        - [MonitorTagsMixin][bigbrotr.services.monitor_tags.MonitorTagsMixin]:
          Kind 30166 tag building.
        - [MonitorPublisherMixin][bigbrotr.services.monitor_publisher.MonitorPublisherMixin]:
          Event signing and broadcasting.
        - [BatchProgressMixin][bigbrotr.services.common.mixins.BatchProgressMixin]:
          Cycle progress tracking.
        - [NetworkSemaphoreMixin][bigbrotr.services.common.mixins.NetworkSemaphoreMixin]:
          Per-network concurrency control.

    See Also:
        [MonitorConfig][bigbrotr.services.monitor.MonitorConfig]:
            Configuration model for this service.
        [Validator][bigbrotr.services.validator.Validator]: Upstream
            service that promotes candidates to the ``relay`` table.
        [Synchronizer][bigbrotr.services.synchronizer.Synchronizer]:
            Downstream service that collects events from monitored relays.
    """

    SERVICE_NAME: ClassVar[ServiceName] = ServiceName.MONITOR
    CONFIG_CLASS: ClassVar[type[MonitorConfig]] = MonitorConfig

    def __init__(self, brotr: Brotr, config: MonitorConfig | None = None) -> None:
        super().__init__(brotr=brotr, config=config)
        self._config: MonitorConfig
        self._keys: Keys = self._config.keys.keys
        self._semaphores: dict[NetworkType, asyncio.Semaphore] = {}
        self._geo_reader: geoip2.database.Reader | None = None
        self._asn_reader: geoip2.database.Reader | None = None
        self._init_progress()

    # -------------------------------------------------------------------------
    # Main Cycle
    # -------------------------------------------------------------------------

    async def run(self) -> None:
        """Execute one complete monitoring cycle.

        Orchestrates: GeoIP update, profile/announcement publishing,
        relay counting, chunk-based health checks, metadata persistence,
        and Kind 30166 event publishing.
        """
        self._progress.reset()
        self._init_semaphores(self._config.networks)

        await self._update_geo_databases()
        await self._open_geo_readers()

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

    async def _update_geo_db_if_stale(
        self, path: Path, url: str, db_name: str, max_age_seconds: float
    ) -> None:
        """Update a single GeoLite2 database if stale or missing.

        Downloads are offloaded to a thread via ``asyncio.to_thread()`` to
        avoid blocking the event loop during large file transfers (10-50MB).
        """
        if await asyncio.to_thread(path.exists):
            age = time.time() - (await asyncio.to_thread(path.stat)).st_mtime
            if age > max_age_seconds:
                age_days = round(age / _SECONDS_PER_DAY, 1)
                self._logger.info("updating_geo_db", db=db_name, age_days=age_days)
                await asyncio.to_thread(_download_geolite_db, url, path)
        else:
            self._logger.info("downloading_geo_db", db=db_name)
            await asyncio.to_thread(_download_geolite_db, url, path)

    async def _update_geo_databases(self) -> None:
        """Download or re-download GeoLite2 databases if missing or stale."""
        compute = self._config.processing.compute
        if not compute.nip66_geo and not compute.nip66_net:
            return

        max_age_days = self._config.geo.max_age_days
        max_age_seconds = max_age_days * _SECONDS_PER_DAY if max_age_days is not None else 0

        if compute.nip66_geo:
            city_path = Path(self._config.geo.city_database_path)
            if not await asyncio.to_thread(city_path.exists):
                self._logger.info("downloading_geo_db", db="city")
                await asyncio.to_thread(
                    _download_geolite_db, self._config.geo.city_download_url, city_path
                )
            elif max_age_days is not None:
                await self._update_geo_db_if_stale(
                    city_path,
                    self._config.geo.city_download_url,
                    "city",
                    max_age_seconds,
                )

        if compute.nip66_net:
            asn_path = Path(self._config.geo.asn_database_path)
            if not await asyncio.to_thread(asn_path.exists):
                self._logger.info("downloading_geo_db", db="asn")
                await asyncio.to_thread(
                    _download_geolite_db, self._config.geo.asn_download_url, asn_path
                )
            elif max_age_days is not None:
                await self._update_geo_db_if_stale(
                    asn_path,
                    self._config.geo.asn_download_url,
                    "asn",
                    max_age_seconds,
                )

    async def _open_geo_readers(self) -> None:
        """Open GeoIP database readers for the current run.

        Reader initialization is offloaded to a thread via ``asyncio.to_thread()``
        because ``geoip2.database.Reader()`` performs synchronous file I/O to
        memory-map the database file.
        """
        if self._config.processing.compute.nip66_geo:
            self._geo_reader = await asyncio.to_thread(
                geoip2.database.Reader, self._config.geo.city_database_path
            )

        if self._config.processing.compute.nip66_net:
            self._asn_reader = await asyncio.to_thread(
                geoip2.database.Reader, self._config.geo.asn_database_path
            )

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
        """Emit Prometheus metrics reflecting current cycle state.

        See Also:
            [Metrics][bigbrotr.core.metrics]: Prometheus endpoint that
                serves the gauge values set here.
        """
        self.set_gauge("total", self._progress.total)
        self.set_gauge("processed", self._progress.processed)
        self.set_gauge("success", self._progress.success)
        self.set_gauge("failure", self._progress.failure)

    # -------------------------------------------------------------------------
    # Counting
    # -------------------------------------------------------------------------

    async def _count_relays(self, networks: list[str]) -> int:
        """Count relays needing health checks for the given networks.

        See Also:
            ``count_relays_due_for_check``: The SQL query executed.
        """
        if not networks:
            self._logger.warning("no_networks_enabled")
            return 0

        threshold = int(self._progress.started_at) - self._config.discovery.interval

        return await count_relays_due_for_check(
            self._brotr,
            self.SERVICE_NAME,
            threshold,
            networks,
        )

    # -------------------------------------------------------------------------
    # Processing
    # -------------------------------------------------------------------------

    async def _process_all(self, networks: list[str]) -> None:
        """Process all pending relays in configurable chunks.

        Iterates until no relays remain, the ``max_relays`` limit is reached,
        or the service is stopped. Each chunk undergoes health checking,
        Kind 30166 publishing, and metadata persistence.

        Note:
            Chunk processing order: ``_check_chunk`` -> ``_publish_relay_discoveries``
            -> ``_persist_results``. Publishing happens before persistence
            so that Kind 30166 events reflect the most recent check data
            even if the DB write fails.
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
        """Fetch the next chunk of relays ordered by least-recently-checked first.

        See Also:
            ``fetch_relays_due_for_check``: The SQL query executed.
        """
        threshold = int(self._progress.started_at) - self._config.discovery.interval

        rows = await fetch_relays_due_for_check(
            self._brotr,
            self.SERVICE_NAME,
            threshold,
            networks,
            limit,
        )

        relays: list[Relay] = []
        for row in rows:
            try:
                relays.append(Relay(row["url"], discovered_at=row["discovered_at"]))
            except (ValueError, TypeError) as e:
                self._logger.warning("parse_failed", url=row["url"], error=str(e))

        return relays

    async def _check_chunk(
        self, relays: list[Relay]
    ) -> tuple[list[tuple[Relay, CheckResult]], list[Relay]]:
        """Run health checks on a chunk of relays concurrently.

        Uses ``asyncio.gather`` with per-network semaphores to bound
        concurrency. A relay is considered successful if any field in
        its [CheckResult][bigbrotr.services.monitor.CheckResult] is
        non-``None``.

        Returns:
            Tuple of (successful relay-result pairs, failed relays).
        """
        tasks = [self._check_one(r) for r in relays]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Re-raise CancelledError — gather(return_exceptions=True) captures it as a result
        for r in results:
            if isinstance(r, asyncio.CancelledError):
                raise r

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
        """Extract success status from a metadata result's logs object."""
        logs = result.logs
        if hasattr(logs, "success"):
            return bool(logs.success)
        if hasattr(logs, "open_success"):
            return bool(logs.open_success)
        return False

    @staticmethod
    def _get_reason(result: Any) -> str | None:
        """Extract failure reason from a metadata result's logs object."""
        logs = result.logs
        if hasattr(logs, "reason"):
            return str(logs.reason) if logs.reason else None
        if hasattr(logs, "open_reason"):
            return str(logs.open_reason) if logs.open_reason else None
        return None

    async def _with_retry(
        self,
        coro_factory: Callable[[], Coroutine[Any, Any, _T]],
        retry_config: MonitorRetryConfig,
        operation: str,
        relay_url: str,
    ) -> _T | None:
        """Execute a metadata fetch with exponential backoff retry.

        Retries on network failures up to ``retry_config.max_attempts`` times.
        Returns the result (possibly with ``success=False``) or ``None`` on
        exception.

        Note:
            The ``coro_factory`` pattern (a callable returning a coroutine)
            is required because Python coroutines are single-use: once
            awaited, they cannot be re-awaited. The factory creates a fresh
            coroutine for each retry attempt.

        Warning:
            Jitter is computed via ``random.uniform()`` (PRNG, ``# noqa: S311``).
            This is intentional -- jitter only needs to decorrelate
            concurrent retries, not provide cryptographic randomness.

        Args:
            coro_factory: Callable that creates the coroutine to execute.
                Must return a fresh coroutine on each call.
            retry_config: [MonitorRetryConfig][bigbrotr.services.monitor.MonitorRetryConfig]
                with max retries, delays, and jitter.
            operation: Operation name for structured log messages.
            relay_url: Relay URL for logging context.

        Returns:
            The metadata result, or ``None`` if an exception occurred.
        """
        max_retries = retry_config.max_attempts
        result = None

        for attempt in range(max_retries + 1):
            try:
                result = await coro_factory()
                if self._get_success(result):
                    return result
            except (TimeoutError, OSError, ValueError, KeyError) as e:
                self._logger.debug(
                    f"{operation}_error",
                    relay=relay_url,
                    attempt=attempt + 1,
                    error=str(e),
                )
                return None

            # Network failure - retry if attempts remaining
            if attempt < max_retries:
                delay = min(retry_config.initial_delay * (2**attempt), retry_config.max_delay)
                jitter = random.uniform(0, retry_config.jitter)  # noqa: S311
                if await self.wait(delay + jitter):
                    return result
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

    @staticmethod
    def _safe_result(results: dict[str, Any], key: str) -> Any:
        """Extract a successful result from asyncio.gather output.

        Returns None if the key is absent or the result is an exception.
        """
        value = results.get(key)
        if value is None or isinstance(value, BaseException):
            return None
        return value

    def _build_parallel_checks(
        self,
        relay: Relay,
        compute: MetadataFlags,
        timeout: float,
        proxy_url: str | None,
    ) -> dict[str, Any]:
        """Build a dict of coroutines for independent health checks.

        Each entry maps a check name to a retry-wrapped coroutine. Only
        checks that are enabled in ``compute`` and applicable to the
        relay's network type are included.

        Note:
            SSL, DNS, Geo, and Net checks are clearnet-only because
            overlay networks (Tor, I2P, Lokinet) do not expose the
            underlying IP address needed for these probes.

        See Also:
            [MetadataFlags][bigbrotr.services.monitor.MetadataFlags]:
                Controls which checks are included.
        """
        tasks: dict[str, Any] = {}

        if compute.nip66_ssl and relay.network == NetworkType.CLEARNET:
            tasks["ssl"] = self._with_retry(
                lambda: Nip66SslMetadata.execute(relay, timeout),
                self._config.processing.retry.nip66_ssl,
                "nip66_ssl",
                relay.url,
            )
        if compute.nip66_dns and relay.network == NetworkType.CLEARNET:
            tasks["dns"] = self._with_retry(
                lambda: Nip66DnsMetadata.execute(relay, timeout),
                self._config.processing.retry.nip66_dns,
                "nip66_dns",
                relay.url,
            )
        if compute.nip66_geo and self._geo_reader and relay.network == NetworkType.CLEARNET:
            geo_reader = self._geo_reader
            precision = self._config.processing.geohash_precision
            tasks["geo"] = self._with_retry(
                lambda: Nip66GeoMetadata.execute(relay, geo_reader, precision),
                self._config.processing.retry.nip66_geo,
                "nip66_geo",
                relay.url,
            )
        if compute.nip66_net and self._asn_reader and relay.network == NetworkType.CLEARNET:
            asn_reader = self._asn_reader
            tasks["net"] = self._with_retry(
                lambda: Nip66NetMetadata.execute(relay, asn_reader),
                self._config.processing.retry.nip66_net,
                "nip66_net",
                relay.url,
            )
        if compute.nip66_http:
            tasks["http"] = self._with_retry(
                lambda: Nip66HttpMetadata.execute(
                    relay,
                    timeout,
                    proxy_url,
                    allow_insecure=self._config.processing.allow_insecure,
                ),
                self._config.processing.retry.nip66_http,
                "nip66_http",
                relay.url,
            )

        return tasks

    async def _check_one(self, relay: Relay) -> CheckResult:
        """Perform all configured health checks on a single relay.

        Runs [Nip11][bigbrotr.nips.nip11.Nip11], RTT, SSL, DNS, geo, net,
        and HTTP checks as configured. Uses the network-specific semaphore
        (from [NetworkSemaphoreMixin][bigbrotr.services.common.mixins.NetworkSemaphoreMixin])
        to limit concurrency.

        Note:
            NIP-11 is fetched first because the RTT write-test may need
            the ``min_pow_difficulty`` from NIP-11's ``limitation`` object
            to apply proof-of-work on the test event. All other checks
            (SSL, DNS, Geo, Net, HTTP) run in parallel after NIP-11 and RTT.

        Returns:
            [CheckResult][bigbrotr.services.monitor.CheckResult] with
            metadata for each completed check (``None`` if skipped/failed).
        """
        empty = CheckResult(None, None, None, None, None, None, None)

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

            def to_relay_meta(
                meta: BaseNipMetadata | None, meta_type: MetadataType
            ) -> RelayMetadata | None:
                if meta is None:
                    return None
                return RelayMetadata(
                    relay=relay,
                    metadata=Metadata(type=meta_type, data=meta.to_dict()),
                    generated_at=generated_at,
                )

            try:
                if compute.nip11_info:
                    nip11 = await self._with_retry(
                        lambda: Nip11.create(
                            relay,
                            timeout=timeout,
                            proxy_url=proxy_url,
                            options=Nip11Options(
                                allow_insecure=self._config.processing.allow_insecure,
                                max_size=self._config.processing.nip11_max_size,
                            ),
                        ),
                        self._config.processing.retry.nip11_info,
                        "nip11_info",
                        relay.url,
                    )

                rtt_meta: Nip66RttMetadata | None = None

                # RTT test: open/read/write round-trip times
                if compute.nip66_rtt:
                    event_builder = EventBuilder(Kind(EventKind.NIP66_TEST), "nip66-test").tags(
                        [Tag.identifier(relay.url)]
                    )
                    # Apply proof-of-work if NIP-11 specifies minimum difficulty
                    if nip11 and nip11.info and nip11.info.logs.success:
                        pow_difficulty = nip11.info.data.limitation.min_pow_difficulty
                        if pow_difficulty and pow_difficulty > 0:
                            event_builder = event_builder.pow(pow_difficulty)
                    read_filter = Filter().limit(1)
                    rtt_deps = Nip66RttDependencies(
                        keys=self._keys,
                        event_builder=event_builder,
                        read_filter=read_filter,
                    )
                    rtt_meta = await self._with_retry(
                        lambda: Nip66RttMetadata.execute(
                            relay,
                            rtt_deps,
                            timeout,
                            proxy_url,
                            allow_insecure=self._config.processing.allow_insecure,
                        ),
                        self._config.processing.retry.nip66_rtt,
                        "nip66_rtt",
                        relay.url,
                    )

                # Run independent checks (SSL, DNS, Geo, Net, HTTP) in parallel
                parallel_tasks = self._build_parallel_checks(relay, compute, timeout, proxy_url)

                gathered: dict[str, Any] = {}
                if parallel_tasks:
                    parallel_results = await asyncio.gather(
                        *parallel_tasks.values(), return_exceptions=True
                    )
                    # Re-raise CancelledError from parallel checks
                    for r in parallel_results:
                        if isinstance(r, asyncio.CancelledError):
                            raise r
                    gathered = dict(zip(parallel_tasks.keys(), parallel_results, strict=True))

                result = CheckResult(
                    nip11=nip11.to_relay_metadata_tuple().nip11_info if nip11 else None,
                    nip66_rtt=to_relay_meta(rtt_meta, MetadataType.NIP66_RTT),
                    nip66_ssl=to_relay_meta(
                        self._safe_result(gathered, "ssl"), MetadataType.NIP66_SSL
                    ),
                    nip66_geo=to_relay_meta(
                        self._safe_result(gathered, "geo"), MetadataType.NIP66_GEO
                    ),
                    nip66_net=to_relay_meta(
                        self._safe_result(gathered, "net"), MetadataType.NIP66_NET
                    ),
                    nip66_dns=to_relay_meta(
                        self._safe_result(gathered, "dns"), MetadataType.NIP66_DNS
                    ),
                    nip66_http=to_relay_meta(
                        self._safe_result(gathered, "http"), MetadataType.NIP66_HTTP
                    ),
                )

                if any(result):
                    self._logger.debug("check_succeeded", url=relay.url)
                else:
                    self._logger.debug("check_failed", url=relay.url)

                return result

            except (TimeoutError, OSError, ValueError, KeyError) as e:
                self._logger.debug("check_error", url=relay.url, error=str(e))
                return empty

    # -------------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------------

    @staticmethod
    def _collect_metadata(
        successful: list[tuple[Relay, CheckResult]],
        store: MetadataFlags,
    ) -> list[RelayMetadata]:
        """Collect storable metadata from successful health check results.

        Iterates over successful check results and collects each metadata type
        that is both present in the result and enabled in the
        [MetadataFlags][bigbrotr.services.monitor.MetadataFlags] store flags.

        Args:
            successful: List of ([Relay][bigbrotr.models.relay.Relay],
                [CheckResult][bigbrotr.services.monitor.CheckResult])
                pairs from health checks.
            store: Flags controlling which metadata types to persist.

        Returns:
            List of [RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata]
            records ready for database insertion.
        """
        metadata: list[RelayMetadata] = []
        for _, result in successful:
            if result.nip11 and store.nip11_info:
                metadata.append(result.nip11)
            if result.nip66_rtt and store.nip66_rtt:
                metadata.append(result.nip66_rtt)
            if result.nip66_ssl and store.nip66_ssl:
                metadata.append(result.nip66_ssl)
            if result.nip66_geo and store.nip66_geo:
                metadata.append(result.nip66_geo)
            if result.nip66_net and store.nip66_net:
                metadata.append(result.nip66_net)
            if result.nip66_dns and store.nip66_dns:
                metadata.append(result.nip66_dns)
            if result.nip66_http and store.nip66_http:
                metadata.append(result.nip66_http)
        return metadata

    async def _persist_results(
        self,
        successful: list[tuple[Relay, CheckResult]],
        failed: list[Relay],
    ) -> None:
        """Persist health check results to the database.

        Inserts [RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata]
        records for successful checks and saves checkpoint timestamps
        (as [ServiceState][bigbrotr.models.service_state.ServiceState]
        records with ``state_type='checkpoint'``) for all checked relays
        (both successful and failed) to avoid re-checking within the
        same interval.

        Note:
            Checkpoints are saved for *all* relays, including failed ones.
            This prevents the monitor from repeatedly retrying a relay
            that is temporarily down within the same discovery interval.
            The relay will be rechecked in the next cycle after the
            interval elapses.
        """
        now = int(time.time())

        # Insert metadata for successful checks
        if successful:
            metadata = self._collect_metadata(successful, self._config.processing.store)
            if metadata:
                try:
                    count = await self._brotr.insert_relay_metadata(metadata)
                    self._logger.debug("metadata_inserted", count=count)
                except (asyncpg.PostgresError, OSError) as e:
                    self._logger.error("metadata_insert_failed", error=str(e), count=len(metadata))

        # Save checkpoints for all checked relays
        all_relays = [relay for relay, _ in successful] + failed
        if all_relays:
            checkpoints: list[ServiceState] = [
                ServiceState(
                    service_name=self.SERVICE_NAME,
                    state_type=ServiceStateType.CHECKPOINT,
                    state_key=relay.url,
                    state_value={"last_check_at": now},
                    updated_at=int(now),
                )
                for relay in all_relays
            ]
            try:
                await self._brotr.upsert_service_state(checkpoints)
            except (asyncpg.PostgresError, OSError) as e:
                self._logger.error("checkpoint_save_failed", error=str(e))


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
    "MonitorProcessingConfig",
    "MonitorPublisherMixin",
    "MonitorRetryConfig",
    "MonitorTagsMixin",
    "ProfileConfig",
    "PublishingConfig",
    "RelayList",
]
