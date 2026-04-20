"""Monitor service configuration models.

See Also:
    [Monitor][bigbrotr.services.monitor.Monitor]: The service class
        that consumes these configurations.
    [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
        Base class providing ``interval`` and ``log_level`` fields.
"""

from __future__ import annotations

from collections.abc import Mapping as MappingABC
from collections.abc import Sequence as SequenceABC
from pathlib import Path
from typing import Annotated, Any, Final, cast

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from bigbrotr.core.base_service import BaseServiceConfig
from bigbrotr.models import Relay
from bigbrotr.models.constants import NetworkType
from bigbrotr.services.common.configs import (
    NetworksConfig,
    NostrKeysConfig,
    parse_relay_list_fail_soft,
)


_CLEARNET_ONLY_FLAGS: Final[tuple[str, ...]] = (
    "nip66_ssl",
    "nip66_geo",
    "nip66_net",
    "nip66_dns",
)


def _reject_bool_alias(value: Any, field_name: str, expected: str) -> Any:
    """Reject boolean aliases for numeric monitor config fields."""
    if isinstance(value, bool):
        raise ValueError(f"{field_name}: expected {expected}, got bool")
    return value


def _normalize_optional_profile_text(value: Any, field_name: str) -> str | None:
    """Trim optional profile text fields and collapse blank payloads to ``None``."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name}: expected string, got {type(value).__name__}")
    normalized = value.strip()
    return normalized or None


def _normalize_optional_geohash(value: Any, field_name: str) -> str | None:
    """Trim optional geohash config payloads and collapse blank values to ``None``."""
    return _normalize_optional_profile_text(value, field_name)


def _normalize_config_string(value: Any, field_name: str, *, allow_blank: bool = False) -> str:
    """Trim config strings while optionally preserving the empty-string unset sentinel."""
    if not isinstance(value, str):
        raise ValueError(f"{field_name}: expected string, got {type(value).__name__}")
    normalized = value.strip()
    if normalized or allow_blank:
        return normalized
    raise ValueError(f"{field_name}: expected non-empty string")


def _require_boolean(value: Any, field_name: str) -> bool:
    """Require canonical booleans for public monitor config boundaries."""
    if not isinstance(value, bool):
        raise ValueError(f"{field_name}: expected boolean, got {type(value).__name__}")
    return value


def _require_string_mapping_keys(value: Any, field_name: str) -> Any:
    """Require canonical string keys for authored monitor mapping boundaries."""
    if not isinstance(value, MappingABC):
        return value
    for key in value:
        if not isinstance(key, str):
            raise ValueError(f"{field_name}: expected string keys, got {type(key).__name__}")
    return value


def _require_number(value: Any, field_name: str) -> int | float:
    """Require canonical numeric types for authored monitor config boundaries."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name}: expected number, got {type(value).__name__}")
    return cast("int | float", value)


def _validate_nonempty_raw_relay_list(data: Any) -> Any:
    """Reject non-empty relay overrides when no valid relay survives normalization."""
    if not isinstance(data, dict) or "relays" not in data:
        return data

    raw = data.get("relays")
    if raw is None or isinstance(raw, Relay):
        return data
    if isinstance(raw, (str, bytes, bytearray)) or not isinstance(raw, SequenceABC):
        return data
    if len(raw) == 0:
        return data

    for item in raw:
        if isinstance(item, Relay):
            return data
        if not isinstance(item, str):
            continue
        try:
            Relay.parse(item)
        except (TypeError, ValueError):
            continue
        return data

    raise ValueError("relays: expected at least one valid relay")


def _reject_non_string_raw_relay_entries(data: Any) -> Any:
    """Reject relay override entries that are neither canonical strings nor Relay objects."""
    if not isinstance(data, dict) or "relays" not in data:
        return data

    raw = data.get("relays")
    if raw is None or isinstance(raw, Relay):
        return data
    if isinstance(raw, (str, bytes, bytearray)) or not isinstance(raw, SequenceABC):
        return data

    for index, item in enumerate(raw):
        if not isinstance(item, (str, Relay)):
            raise ValueError(
                f"relays[{index}]: expected string or Relay, got {type(item).__name__}"
            )
    return data


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

    nip11_info: bool = Field(default=True, description="NIP-11 relay information document")
    nip66_rtt: bool = Field(default=True, description="NIP-66 round-trip time measurement")
    nip66_ssl: bool = Field(default=True, description="NIP-66 SSL/TLS certificate inspection")
    nip66_geo: bool = Field(default=True, description="NIP-66 geolocation lookup")
    nip66_net: bool = Field(default=True, description="NIP-66 network/ASN lookup")
    nip66_dns: bool = Field(default=True, description="NIP-66 DNS resolution")
    nip66_http: bool = Field(default=True, description="NIP-66 HTTP server headers")

    @model_validator(mode="before")
    @classmethod
    def _require_string_field_keys(cls, data: Any) -> Any:
        return _require_string_mapping_keys(data, "config")

    @field_validator(
        "nip11_info",
        "nip66_rtt",
        "nip66_ssl",
        "nip66_geo",
        "nip66_net",
        "nip66_dns",
        "nip66_http",
        mode="before",
    )
    @classmethod
    def reject_boolean_flag_aliases(cls, value: Any, info: ValidationInfo) -> bool:
        """Require canonical booleans for monitor metadata flag boundaries."""
        field_name = info.field_name or "value"
        return _require_boolean(value, field_name)

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
        [retry_fetch][bigbrotr.services.monitor.utils.retry_fetch]:
            The function that consumes these settings.
    """

    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(
        default=0, ge=0, le=10, description="Maximum retry attempts (0 = no retries)"
    )
    initial_delay: float = Field(
        default=1.0, ge=0.1, le=10.0, description="Initial delay between retries in seconds"
    )
    max_delay: float = Field(
        default=10.0, ge=1.0, le=60.0, description="Maximum delay between retries in seconds"
    )
    jitter: float = Field(
        default=0.5, ge=0.0, le=2.0, description="Random jitter factor for retry delay"
    )

    @model_validator(mode="before")
    @classmethod
    def require_string_field_keys(cls, data: Any) -> Any:
        """Reject raw retry payloads with non-string mapping keys."""
        return _require_string_mapping_keys(data, "config")

    @field_validator("max_attempts", mode="before")
    @classmethod
    def require_integer_max_attempts(cls, v: Any, info: ValidationInfo) -> int:
        """Require canonical integers for retry-attempt authored boundaries."""
        field_name = info.field_name or "max_attempts"
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError(f"{field_name}: expected integer, got {type(v).__name__}")
        return cast("int", v)

    @field_validator("initial_delay", "max_delay", "jitter", mode="before")
    @classmethod
    def require_numeric_retry_timings(cls, v: Any, info: ValidationInfo) -> int | float:
        """Require canonical numeric types for retry timing controls."""
        field_name = info.field_name or "value"
        return _require_number(v, field_name)

    @field_validator("max_delay")
    @classmethod
    def validate_max_delay(cls, v: float, info: ValidationInfo) -> float:
        """Ensure max_delay >= initial_delay."""
        initial_delay = info.data.get("initial_delay", 1.0)
        if v < initial_delay:
            raise ValueError(f"max_delay ({v}) must be >= initial_delay ({initial_delay})")
        return v


class RetriesConfig(BaseModel):
    """Per-metadata-type retry settings.

    Each field corresponds to one of the seven health check types and
    holds a [RetryConfig][bigbrotr.services.monitor.configs.RetryConfig]
    with independent ``max_attempts``, ``initial_delay``, ``max_delay``,
    and ``jitter`` values.

    See Also:
        [ProcessingConfig][bigbrotr.services.monitor.ProcessingConfig]:
            Parent config that embeds this model.
    """

    model_config = ConfigDict(extra="forbid")

    nip11_info: RetryConfig = Field(
        default_factory=RetryConfig, description="Retry settings for NIP-11 info fetch"
    )
    nip66_rtt: RetryConfig = Field(
        default_factory=RetryConfig, description="Retry settings for RTT measurement"
    )
    nip66_ssl: RetryConfig = Field(
        default_factory=RetryConfig, description="Retry settings for SSL inspection"
    )
    nip66_geo: RetryConfig = Field(
        default_factory=RetryConfig, description="Retry settings for geolocation lookup"
    )
    nip66_net: RetryConfig = Field(
        default_factory=RetryConfig, description="Retry settings for network/ASN lookup"
    )
    nip66_dns: RetryConfig = Field(
        default_factory=RetryConfig, description="Retry settings for DNS resolution"
    )
    nip66_http: RetryConfig = Field(
        default_factory=RetryConfig, description="Retry settings for HTTP header extraction"
    )

    @model_validator(mode="before")
    @classmethod
    def require_string_field_keys(cls, data: Any) -> Any:
        """Reject raw retries payloads with non-string mapping keys."""
        return _require_string_mapping_keys(data, "config")


class ProcessingConfig(BaseModel):
    """Processing settings: chunk size, retry policies, and compute/store flags.

    See Also:
        [MonitorConfig][bigbrotr.services.monitor.MonitorConfig]: Parent
            config that embeds this model.
        [MetadataFlags][bigbrotr.services.monitor.MetadataFlags]: The
            ``compute`` and ``store`` flag sets.
    """

    model_config = ConfigDict(extra="forbid")

    chunk_size: int = Field(
        default=100, ge=10, le=1000, description="Relays to process before flushing results"
    )
    max_relays: int | None = Field(
        default=None, ge=1, description="Maximum relays per cycle (None = all)"
    )
    allow_insecure: bool = Field(
        default=False, description="Allow unverified SSL for clearnet relays"
    )
    nip11_info_max_size: int = Field(
        default=1_048_576,
        ge=1024,
        le=10_485_760,
        description="Maximum NIP-11 response body size in bytes",
    )
    retries: RetriesConfig = Field(
        default_factory=RetriesConfig, description="Per-metadata-type retry settings"
    )
    compute: MetadataFlags = Field(
        default_factory=MetadataFlags, description="Which metadata types to compute"
    )
    store: MetadataFlags = Field(
        default_factory=MetadataFlags, description="Which metadata types to persist"
    )

    @model_validator(mode="before")
    @classmethod
    def require_string_field_keys(cls, data: Any) -> Any:
        """Reject raw processing payloads with non-string mapping keys."""
        return _require_string_mapping_keys(data, "config")

    @field_validator("chunk_size", mode="before")
    @classmethod
    def require_integer_chunk_size(cls, v: Any, info: ValidationInfo) -> int:
        """Require canonical integers for the authored flush-batch size."""
        field_name = info.field_name or "chunk_size"
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError(f"{field_name}: expected integer, got {type(v).__name__}")
        return cast("int", v)

    @field_validator("nip11_info_max_size", mode="before")
    @classmethod
    def require_integer_nip11_info_max_size(cls, v: Any, info: ValidationInfo) -> int:
        """Require canonical integers for the authored NIP-11 body-size cap."""
        field_name = info.field_name or "nip11_info_max_size"
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError(f"{field_name}: expected integer, got {type(v).__name__}")
        return cast("int", v)

    @field_validator("max_relays", mode="before")
    @classmethod
    def require_integer_max_relays(cls, v: Any, info: ValidationInfo) -> int | None:
        """Require canonical integers for the authored per-cycle relay cap."""
        if v is None:
            return v
        field_name = info.field_name or "max_relays"
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError(f"{field_name}: expected integer, got {type(v).__name__}")
        return cast("int", v)

    @field_validator("allow_insecure", mode="before")
    @classmethod
    def reject_non_boolean_allow_insecure(cls, v: Any, info: ValidationInfo) -> bool:
        """Require an explicit boolean for the insecure transport policy."""
        field_name = info.field_name or "allow_insecure"
        return _require_boolean(v, field_name)


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

    model_config = ConfigDict(extra="forbid")

    city_database_path: str = Field(
        default="static/GeoLite2-City.mmdb",
        min_length=1,
        description="Path to GeoLite2 City database",
    )
    asn_database_path: str = Field(
        default="static/GeoLite2-ASN.mmdb",
        min_length=1,
        description="Path to GeoLite2 ASN database",
    )
    city_download_url: str = Field(
        default="https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-City.mmdb",
        description="Download URL for GeoLite2 City database",
    )
    asn_download_url: str = Field(
        default="https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-ASN.mmdb",
        description="Download URL for GeoLite2 ASN database",
    )
    max_age_days: int | None = Field(
        default=30, ge=1, description="Re-download databases older than this (None = never)"
    )
    max_download_size: int = Field(
        default=100_000_000,
        ge=1_000_000,
        le=500_000_000,
        description="Maximum download size per database file in bytes (default: 100 MB)",
    )
    geohash_precision: int = Field(
        default=9, ge=1, le=12, description="Geohash precision (9=~4.77m)"
    )

    @model_validator(mode="before")
    @classmethod
    def _require_string_field_keys(cls, data: Any) -> Any:
        return _require_string_mapping_keys(data, "config")

    @field_validator("city_database_path", "asn_database_path", mode="before")
    @classmethod
    def normalize_database_paths(cls, value: Any, info: ValidationInfo) -> str:
        """Trim GeoLite database paths and reject blank payloads."""
        field_name = info.field_name or "value"
        return _normalize_config_string(value, field_name)

    @field_validator("city_download_url", "asn_download_url", mode="before")
    @classmethod
    def normalize_download_urls(cls, value: Any, info: ValidationInfo) -> str:
        """Trim download URLs while preserving the empty-string unset sentinel."""
        field_name = info.field_name or "value"
        return _normalize_config_string(value, field_name, allow_blank=True)

    @field_validator("max_age_days", "max_download_size", "geohash_precision", mode="before")
    @classmethod
    def require_integer_geo_numerics(cls, v: Any, info: ValidationInfo) -> int | None:
        """Require canonical integers for authored geo numeric boundaries."""
        if v is None:
            return v
        field_name = info.field_name or "value"
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError(f"{field_name}: expected integer, got {type(v).__name__}")
        return cast("int", v)


class PublishingConfig(BaseModel):
    """Default relay list used as fallback for event publishing.

    See Also:
        [DiscoveryConfig][bigbrotr.services.monitor.DiscoveryConfig],
        [AnnouncementConfig][bigbrotr.services.monitor.AnnouncementConfig],
        [ProfileConfig][bigbrotr.services.monitor.ProfileConfig]: Each
            can override this list with their own ``relays`` field.
    """

    model_config = ConfigDict(extra="forbid")

    relays: Annotated[
        list[Relay],
        BeforeValidator(parse_relay_list_fail_soft),
    ] = Field(
        default_factory=lambda: [
            Relay("wss://relay.mostr.pub"),
            Relay("wss://relay.damus.io"),
            Relay("wss://nos.lol"),
            Relay("wss://relay.primal.net"),
        ],
        description="Default relay list for event publishing",
    )

    @model_validator(mode="before")
    @classmethod
    def reject_invalid_nonempty_relays(cls, data: Any) -> Any:
        """Reject non-empty publishing relay overrides when nothing valid remains."""
        return _validate_nonempty_raw_relay_list(
            _reject_non_string_raw_relay_entries(_require_string_mapping_keys(data, "config"))
        )


class DiscoveryConfig(BaseModel):
    """Kind 30166 relay discovery event settings (NIP-66).

    See Also:
        [build_relay_discovery][bigbrotr.nips.event_builders.build_relay_discovery]:
            Builds the event from check results using ``include`` flags.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=True, description="Enable Kind 30166 relay discovery publishing")
    interval: float = Field(
        default=14_400.0,
        ge=60.0,
        le=604800.0,
        description="Minimum seconds between discovery publishes",
    )
    include: MetadataFlags = Field(
        default_factory=MetadataFlags,
        description="Which metadata types to include in discovery events",
    )
    relays: Annotated[
        list[Relay] | None,
        BeforeValidator(parse_relay_list_fail_soft),
    ] = Field(default=None, description="Override relay list (None = use publishing default)")

    @model_validator(mode="before")
    @classmethod
    def reject_invalid_nonempty_relays(cls, data: Any) -> Any:
        """Reject non-empty discovery relay overrides when nothing valid remains."""
        return _validate_nonempty_raw_relay_list(
            _reject_non_string_raw_relay_entries(_require_string_mapping_keys(data, "config"))
        )

    @field_validator("enabled", mode="before")
    @classmethod
    def reject_non_boolean_enabled(cls, value: Any, info: ValidationInfo) -> bool:
        """Require a canonical boolean for discovery publish toggles."""
        field_name = info.field_name or "enabled"
        return _require_boolean(value, field_name)

    @field_validator("interval", mode="before")
    @classmethod
    def require_numeric_interval(cls, value: Any, info: ValidationInfo) -> int | float:
        """Require canonical numeric types for discovery publish intervals."""
        field_name = info.field_name or "interval"
        return _require_number(value, field_name)


class AnnouncementConfig(BaseModel):
    """Kind 10166 monitor announcement settings (NIP-66).

    See Also:
        [build_monitor_announcement][bigbrotr.nips.event_builders.build_monitor_announcement]:
            Builds the announcement event with frequency and timeout tags.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=True, description="Enable Kind 10166 monitor announcement")
    interval: float = Field(
        default=86_400.0,
        ge=60.0,
        le=604800.0,
        description="Minimum seconds between announcements",
    )
    geohash: str | None = Field(
        default=None,
        description="NIP-52 geohash of the monitor's location (None = omit from announcement)",
    )
    include: MetadataFlags = Field(
        default_factory=MetadataFlags,
        description="Which metadata types to include in announcement",
    )
    relays: Annotated[
        list[Relay] | None,
        BeforeValidator(parse_relay_list_fail_soft),
    ] = Field(default=None, description="Override relay list (None = use publishing default)")

    @model_validator(mode="before")
    @classmethod
    def reject_invalid_nonempty_relays(cls, data: Any) -> Any:
        """Reject non-empty announcement relay overrides when nothing valid remains."""
        return _validate_nonempty_raw_relay_list(
            _reject_non_string_raw_relay_entries(_require_string_mapping_keys(data, "config"))
        )

    @field_validator("enabled", mode="before")
    @classmethod
    def reject_non_boolean_enabled(cls, value: Any, info: ValidationInfo) -> bool:
        """Require a canonical boolean for announcement publish toggles."""
        field_name = info.field_name or "enabled"
        return _require_boolean(value, field_name)

    @field_validator("interval", mode="before")
    @classmethod
    def require_numeric_interval(cls, value: Any, info: ValidationInfo) -> int | float:
        """Require canonical numeric types for announcement publish intervals."""
        field_name = info.field_name or "interval"
        return _require_number(value, field_name)

    @field_validator("geohash", mode="before")
    @classmethod
    def normalize_geohash(cls, value: Any, info: ValidationInfo) -> str | None:
        """Trim optional geohash payloads before the public builder consumes them."""
        field_name = info.field_name or "geohash"
        return _normalize_optional_geohash(value, field_name)


class ProfileConfig(BaseModel):
    """Kind 0 profile metadata settings (NIP-01).

    See Also:
        [build_profile_event][bigbrotr.nips.event_builders.build_profile_event]:
            Builds the profile event from these fields.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=True, description="Enable Kind 0 profile publishing")
    interval: float = Field(
        default=86_400.0,
        ge=60.0,
        le=604800.0,
        description="Minimum seconds between profile publishes",
    )
    relays: Annotated[
        list[Relay] | None,
        BeforeValidator(parse_relay_list_fail_soft),
    ] = Field(default=None, description="Override relay list (None = use publishing default)")
    name: str | None = Field(
        default="BigBrotr Monitor", description="Display name for the monitor profile"
    )
    about: str | None = Field(
        default="Nostr relay monitoring service", description="Description for the monitor profile"
    )
    picture: str | None = Field(default=None, description="Profile picture URL")
    nip05: str | None = Field(default=None, description="NIP-05 identifier")
    website: str | None = Field(default=None, description="Website URL")
    banner: str | None = Field(default=None, description="Banner image URL")
    lud16: str | None = Field(default=None, description="Lightning address (LNURL)")

    @model_validator(mode="before")
    @classmethod
    def reject_invalid_nonempty_relays(cls, data: Any) -> Any:
        """Reject non-empty profile relay overrides when nothing valid remains."""
        return _validate_nonempty_raw_relay_list(
            _reject_non_string_raw_relay_entries(_require_string_mapping_keys(data, "config"))
        )

    @field_validator(
        "name",
        "about",
        "picture",
        "nip05",
        "website",
        "banner",
        "lud16",
        mode="before",
    )
    @classmethod
    def profile_text_fields_valid(cls, value: Any, info: ValidationInfo) -> str | None:
        return _normalize_optional_profile_text(value, str(info.field_name))

    @field_validator("enabled", mode="before")
    @classmethod
    def reject_non_boolean_enabled(cls, value: Any, info: ValidationInfo) -> bool:
        """Require a canonical boolean for profile publish toggles."""
        field_name = info.field_name or "enabled"
        return _require_boolean(value, field_name)

    @field_validator("interval", mode="before")
    @classmethod
    def require_numeric_interval(cls, value: Any, info: ValidationInfo) -> int | float:
        """Require canonical numeric types for profile publish intervals."""
        field_name = info.field_name or "interval"
        return _require_number(value, field_name)


class RelayListConfig(BaseModel):
    """Kind 10002 relay list metadata settings (NIP-65)."""

    enabled: bool = Field(default=True, description="Enable Kind 10002 relay list publishing")
    interval: float = Field(
        default=86_400.0,
        ge=60.0,
        le=604800.0,
        description="Minimum seconds between relay list publishes",
    )
    relays: Annotated[
        list[Relay] | None,
        BeforeValidator(parse_relay_list_fail_soft),
    ] = Field(default=None, description="Override relay list (None = use publishing default)")

    @model_validator(mode="before")
    @classmethod
    def reject_invalid_nonempty_relays(cls, data: Any) -> Any:
        """Reject non-empty relay-list overrides when nothing valid remains."""
        return _validate_nonempty_raw_relay_list(
            _reject_non_string_raw_relay_entries(_require_string_mapping_keys(data, "config"))
        )

    @field_validator("enabled", mode="before")
    @classmethod
    def reject_non_boolean_enabled(cls, value: Any, info: ValidationInfo) -> bool:
        """Require a canonical boolean for relay-list publish toggles."""
        field_name = info.field_name or "enabled"
        return _require_boolean(value, field_name)

    @field_validator("interval", mode="before")
    @classmethod
    def require_numeric_interval(cls, value: Any, info: ValidationInfo) -> int | float:
        """Require canonical numeric types for relay-list publish intervals."""
        field_name = info.field_name or "interval"
        return _require_number(value, field_name)


class MonitorConfig(BaseServiceConfig):
    """Monitor service configuration with validation for dependency constraints.

    Note:
        Four ``model_validator`` methods enforce dependency constraints
        at config load time (fail-fast):

        - ``validate_geo_databases``: GeoLite2 files must be downloadable.
        - ``validate_clearnet_only_checks``: Clearnet-only compute flags
          require the clearnet network to be enabled.
        - ``validate_store_requires_compute``: Cannot store uncalculated
          metadata.
        - ``validate_publish_requires_compute``: Cannot publish uncalculated
          metadata.

    See Also:
        [Monitor][bigbrotr.services.monitor.Monitor]: The service class
            that consumes this configuration.
        [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
            Base class providing ``interval``, ``max_consecutive_failures``, and ``metrics`` fields.
        [NostrKeysConfig][bigbrotr.services.common.configs.NostrKeysConfig]: Nostr key
            management for event signing.
    """

    networks: NetworksConfig = Field(
        default_factory=NetworksConfig, description="Per-network connection settings"
    )
    keys: NostrKeysConfig = Field(
        default_factory=lambda: NostrKeysConfig(keys_env="NOSTR_PRIVATE_KEY_MONITOR"),
        description="Nostr key configuration for event signing",
    )
    processing: ProcessingConfig = Field(
        default_factory=ProcessingConfig, description="Processing and health check settings"
    )
    geo: GeoConfig = Field(default_factory=GeoConfig, description="GeoLite2 database settings")
    publishing: PublishingConfig = Field(
        default_factory=PublishingConfig, description="Default event publishing settings"
    )
    discovery: DiscoveryConfig = Field(
        default_factory=DiscoveryConfig, description="Kind 30166 relay discovery settings"
    )
    announcement: AnnouncementConfig = Field(
        default_factory=AnnouncementConfig, description="Kind 10166 monitor announcement settings"
    )
    profile: ProfileConfig = Field(
        default_factory=ProfileConfig, description="Kind 0 profile metadata settings"
    )
    relay_list: RelayListConfig = Field(
        default_factory=RelayListConfig, description="Kind 10002 relay list metadata settings"
    )

    @model_validator(mode="before")
    @classmethod
    def require_string_field_keys(cls, data: Any) -> Any:
        """Reject raw monitor payloads with non-string mapping keys."""
        return _require_string_mapping_keys(data, "config")

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
    def validate_clearnet_only_checks(self) -> MonitorConfig:
        """Ensure clearnet-only compute flags are disabled when clearnet is off."""
        if self.networks.is_enabled(NetworkType.CLEARNET):
            return self
        enabled = [f for f in _CLEARNET_ONLY_FLAGS if getattr(self.processing.compute, f)]
        if enabled:
            raise ValueError(
                f"Clearnet is disabled but these clearnet-only checks are enabled "
                f"in processing.compute: {', '.join(enabled)}. "
                f"Disable them or enable the clearnet network."
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
        if self.discovery.enabled:
            errors = self.discovery.include.get_missing_from(self.processing.compute)
            if errors:
                raise ValueError(
                    f"Cannot publish metadata that is not computed: {', '.join(errors)}. "
                    "Enable in processing.compute.* or disable in discovery.include.*"
                )
        if self.announcement.enabled:
            errors = self.announcement.include.get_missing_from(self.processing.compute)
            if errors:
                raise ValueError(
                    f"Cannot announce metadata that is not computed: {', '.join(errors)}. "
                    "Enable in processing.compute.* or disable in announcement.include.*"
                )
        return self
