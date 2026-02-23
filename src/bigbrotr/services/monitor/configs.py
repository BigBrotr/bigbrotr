"""Monitor service configuration models.

See Also:
    [Monitor][bigbrotr.services.monitor.Monitor]: The service class
        that consumes these configurations.
    [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
        Base class providing ``interval`` and ``log_level`` fields.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field, model_validator

from bigbrotr.core.base_service import BaseServiceConfig
from bigbrotr.models import Relay
from bigbrotr.services.common.configs import NetworksConfig
from bigbrotr.utils.keys import KeysConfig
from bigbrotr.utils.parsing import models_from_db_params


class MetadataFlags(BaseModel):
    """Boolean flags controlling which metadata types to compute, store, or publish.

    Used in three contexts within
    [ProcessingConfig][bigbrotr.services.monitor.ProcessingConfig]:
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


class RetryConfig(BaseModel):
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


class RetriesConfig(BaseModel):
    """Per-metadata-type retry settings.

    Each field corresponds to one of the seven health check types and
    holds a [RetryConfig][bigbrotr.services.monitor.RetryConfig]
    with independent ``max_attempts``, ``initial_delay``, ``max_delay``,
    and ``jitter`` values.

    See Also:
        [ProcessingConfig][bigbrotr.services.monitor.ProcessingConfig]:
            Parent config that embeds this model.
    """

    nip11_info: RetryConfig = Field(default_factory=RetryConfig)
    nip66_rtt: RetryConfig = Field(default_factory=RetryConfig)
    nip66_ssl: RetryConfig = Field(default_factory=RetryConfig)
    nip66_geo: RetryConfig = Field(default_factory=RetryConfig)
    nip66_net: RetryConfig = Field(default_factory=RetryConfig)
    nip66_dns: RetryConfig = Field(default_factory=RetryConfig)
    nip66_http: RetryConfig = Field(default_factory=RetryConfig)


class ProcessingConfig(BaseModel):
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
    nip11_info_max_size: int = Field(default=1_048_576, ge=1024, le=10_485_760)
    retries: RetriesConfig = Field(default_factory=RetriesConfig)
    compute: MetadataFlags = Field(default_factory=MetadataFlags)
    store: MetadataFlags = Field(default_factory=MetadataFlags)


class GeoConfig(BaseModel):
    """GeoLite2 database paths, download URLs, and staleness settings.

    Note:
        GeoLite2 databases are downloaded at the start of each cycle if
        missing or stale (older than ``max_age_days``). Downloads use
        async HTTP via ``aiohttp`` with bounded reads to prevent memory
        exhaustion from oversized payloads.

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
    max_download_size: int = Field(
        default=100_000_000,
        ge=1_000_000,
        le=500_000_000,
        description="Maximum download size per database file in bytes (default: 100 MB)",
    )
    geohash_precision: int = Field(
        default=9, ge=1, le=12, description="Geohash precision (9=~4.77m)"
    )


class PublishingConfig(BaseModel):
    """Default relay list used as fallback for event publishing.

    See Also:
        [DiscoveryConfig][bigbrotr.services.monitor.DiscoveryConfig],
        [AnnouncementConfig][bigbrotr.services.monitor.AnnouncementConfig],
        [ProfileConfig][bigbrotr.services.monitor.ProfileConfig]: Each
            can override this list with their own ``relays`` field.
    """

    relays: Annotated[
        list[Relay],
        BeforeValidator(lambda v: models_from_db_params(v, Relay)),
    ] = Field(default_factory=list)
    timeout: float = Field(default=30.0, gt=0, description="Broadcast timeout in seconds")


class DiscoveryConfig(BaseModel):
    """Kind 30166 relay discovery event settings (NIP-66).

    See Also:
        [build_relay_discovery][bigbrotr.nips.event_builders.build_relay_discovery]:
            Builds the event from check results using ``include`` flags.
    """

    enabled: bool = Field(default=True)
    interval: int = Field(default=3600, ge=60)
    include: MetadataFlags = Field(default_factory=MetadataFlags)
    relays: Annotated[
        list[Relay],
        BeforeValidator(lambda v: models_from_db_params(v, Relay)),
    ] = Field(default_factory=list)  # Overrides publishing.relays


class AnnouncementConfig(BaseModel):
    """Kind 10166 monitor announcement settings (NIP-66).

    See Also:
        [build_monitor_announcement][bigbrotr.nips.event_builders.build_monitor_announcement]:
            Builds the announcement event with frequency and timeout tags.
    """

    enabled: bool = Field(default=True)
    interval: int = Field(default=86_400, ge=60)
    relays: Annotated[
        list[Relay],
        BeforeValidator(lambda v: models_from_db_params(v, Relay)),
    ] = Field(default_factory=list)


class ProfileConfig(BaseModel):
    """Kind 0 profile metadata settings (NIP-01).

    See Also:
        [build_profile_event][bigbrotr.nips.event_builders.build_profile_event]:
            Builds the profile event from these fields.
    """

    enabled: bool = Field(default=False)
    interval: int = Field(default=86_400, ge=60)
    relays: Annotated[
        list[Relay],
        BeforeValidator(lambda v: models_from_db_params(v, Relay)),
    ] = Field(default_factory=list)
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

    networks: NetworksConfig = Field(default_factory=NetworksConfig)
    keys: KeysConfig = Field(default_factory=lambda: KeysConfig.model_validate({}))
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    geo: GeoConfig = Field(default_factory=GeoConfig)
    publishing: PublishingConfig = Field(default_factory=PublishingConfig)
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    announcement: AnnouncementConfig = Field(default_factory=AnnouncementConfig)
    profile: ProfileConfig = Field(default_factory=ProfileConfig)

    @model_validator(mode="after")
    def validate_geo_databases(self) -> MonitorConfig:
        """Validate GeoLite2 database paths have download URLs if files are missing.

        Actual downloads are deferred to ``_update_geo_databases()`` which
        downloads asynchronously via ``aiohttp``.
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
