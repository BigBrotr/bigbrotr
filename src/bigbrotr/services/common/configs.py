"""Shared configuration models for BigBrotr services.

Provides:

- per-network runtime settings (clearnet, Tor, I2P, Lokinet);
- shared Nostr signing-key config;
- public-adapter exposure policy models for API/DVM-style read surfaces.

Each network type has its own config class with sensible defaults, allowing
partial YAML overrides (e.g., setting only ``tor.enabled: true`` inherits the
default ``proxy_url``).

The network type is determined by the
[NetworkType][bigbrotr.models.constants.NetworkType] enum, and the relay's
network is auto-detected from its URL scheme and hostname by the
[Relay][bigbrotr.models.relay.Relay] model.

The module also centralizes the shared public-adapter contract for:

- default/max page-size validation;
- legacy `tables` rejection;
- normalization of adapter-local protocol exposure policy over canonical
  public readable-resource IDs.

See Also:
    [NetworkType][bigbrotr.models.constants.NetworkType]: Enum that
        identifies each overlay network.
    [NetworkSemaphoresMixin][bigbrotr.services.common.mixins.NetworkSemaphoresMixin]:
        Uses ``max_tasks`` to create per-network concurrency semaphores.
    [PublicReadAdapterConfig][bigbrotr.services.common.configs.PublicReadAdapterConfig]:
        Shared API/DVM config base for public readable-resource exposure.
    [ValidatorConfig][bigbrotr.services.validator.ValidatorConfig],
    [MonitorConfig][bigbrotr.services.monitor.MonitorConfig],
    [SynchronizerConfig][bigbrotr.services.synchronizer.SynchronizerConfig]:
        Service configs that embed ``NetworksConfig``.

Examples:
    ```yaml
    networks:
      clearnet:
        enabled: true
        max_tasks: 100
      tor:
        enabled: true  # Inherits default proxy_url
    ```
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, ClassVar, cast

from nostr_sdk import Keys
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from bigbrotr.core.base_service import BaseServiceConfig
from bigbrotr.models import Relay
from bigbrotr.models.constants import NetworkType
from bigbrotr.utils.keys import load_keys_from_env
from bigbrotr.utils.protocol_proxy import normalize_proxy_url


logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from bigbrotr.services.common.read_models import ReadSurface


def _reject_bool_alias(value: Any, field_name: str, expected: str) -> Any:
    """Reject boolean values for numeric config fields before pydantic coercion."""
    if isinstance(value, bool):
        raise ValueError(f"{field_name}: expected {expected}, got bool")
    return value


def _require_bool(value: Any, field_name: str) -> bool:
    """Require canonical booleans for public service config boundaries."""
    if not isinstance(value, bool):
        raise ValueError(f"{field_name}: expected boolean, got {type(value).__name__}")
    return value


def _require_int(value: Any, field_name: str) -> int:
    """Require canonical integers for authored config boundaries."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name}: expected integer, got {type(value).__name__}")
    return cast("int", value)


def _require_number(value: Any, field_name: str) -> int | float:
    """Require canonical numeric types for authored config boundaries."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name}: expected number, got {type(value).__name__}")
    return cast("int | float", value)


def _normalize_optional_proxy_url(value: Any) -> str | None:
    """Normalize optional authored proxy URLs against the shared protocol contract."""
    return normalize_proxy_url(value)


def _normalize_optional_env_name(value: Any, field_name: str) -> str | None:
    """Normalize optional authored environment-variable names."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name}: expected string, got {type(value).__name__}")
    normalized = value.strip()
    return normalized or None


def _require_string_mapping_keys(value: Any, field_name: str) -> Any:
    """Require canonical string keys for authored mapping boundaries."""
    if not isinstance(value, Mapping):
        return value
    for key in value:
        if not isinstance(key, str):
            raise ValueError(f"{field_name}: expected string keys, got {type(key).__name__}")
    return value


def parse_relay_list_fail_soft(raw: object) -> list[Relay] | None:
    """Parse one config value into canonical relays, skipping invalid entries."""
    if raw is None:
        return None
    if isinstance(raw, Relay):
        return [raw]
    if isinstance(raw, (str, bytes, bytearray)) or not isinstance(raw, Sequence):
        raise TypeError("Relay list must be a sequence of relay URLs")

    relays: list[Relay] = []
    for item in raw:
        if isinstance(item, Relay):
            relays.append(item)
            continue
        if not isinstance(item, str):
            logger.warning("invalid_relay_config_entry item_type=%s", type(item).__name__)
            continue
        try:
            relays.append(Relay.parse(item))
        except (TypeError, ValueError) as e:
            logger.warning("invalid_relay_config_entry relay=%s error=%s", item, e)
    return relays


class NostrKeysConfig(BaseModel):
    """Shared Nostr signing-key config for services that publish or authenticate."""

    model_config = {"arbitrary_types_allowed": True}

    keys_env: str | None = Field(
        default=None,
        description="Environment variable name for private key",
    )
    keys: Keys = Field(
        default_factory=Keys.generate,
        description="Keys loaded from keys_env, or generated when unset/blank",
    )

    def __repr__(self) -> str:
        """Redact private key material and show whether keys are configured."""
        keys = getattr(self, "keys", None)
        if keys is None:
            return f"NostrKeysConfig(keys_env={self.keys_env!r}, pubkey=None)"
        pubkey = keys.public_key().to_hex()
        return f"NostrKeysConfig(keys_env={self.keys_env!r}, pubkey={pubkey!r})"

    def __str__(self) -> str:
        """Redact private key material — show only the public key."""
        return self.__repr__()

    @field_validator("keys_env", mode="before")
    @classmethod
    def normalize_keys_env(cls, value: Any, info: ValidationInfo) -> str | None:
        """Canonicalize optional env-var names and reject non-string aliases."""
        field_name = info.field_name or "value"
        return _normalize_optional_env_name(value, field_name)

    @model_validator(mode="before")
    @classmethod
    def _load_keys_from_env(cls, data: Any) -> Any:
        """Resolve ``keys`` from ``keys_env`` when the caller did not provide them."""
        if not isinstance(data, dict):
            return data

        _require_string_mapping_keys(data, "config")
        data = dict(data)

        data["keys_env"] = _normalize_optional_env_name(data.get("keys_env"), "keys_env")

        if data.get("keys") is not None:
            return data

        data.pop("keys", None)

        env_var = data.get("keys_env")
        if not isinstance(env_var, str):
            return data

        keys = load_keys_from_env(env_var)
        if keys is not None:
            data["keys"] = keys
        return data


class ReadModelPolicy(BaseModel):
    """Per-readable-resource access and pricing policy for public adapters.

    This model is the unit of one adapter-local protocol exposure policy.
    Public adapters still accept the historical ``read_models`` YAML key, but
    the underlying concept is broader: a per-protocol decision about which
    readable resources are exposed and, where relevant, how they are priced.

    Resources default to disabled (not exposed). Only resources explicitly
    listed with ``enabled: true`` in the service YAML config are served.

    Attributes:
        enabled: Whether this readable resource is exposed on the adapter.
            Disabled resources return 404 in the API and error feedback in the DVM.
        price: Price in millisats.  ``0`` means free (no payment required).
            Used by the DVM service for NIP-90 bid/payment-required.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=False, description="Whether this readable resource is exposed")
    price: int = Field(default=0, ge=0, description="Price in millisats (0 = free)")

    @model_validator(mode="before")
    @classmethod
    def _require_string_field_keys(cls, data: Any) -> Any:
        return _require_string_mapping_keys(data, "config")

    @field_validator("enabled", mode="before")
    @classmethod
    def _require_boolean_enabled(cls, value: Any, info: ValidationInfo) -> bool:
        field_name = info.field_name or "value"
        if not isinstance(value, bool):
            raise ValueError(f"{field_name}: expected boolean, got {type(value).__name__}")
        return value

    @field_validator("price", mode="before")
    @classmethod
    def _require_integer_price(cls, value: Any, info: ValidationInfo) -> int:
        field_name = info.field_name or "value"
        return _require_int(value, field_name)


def normalize_protocol_exposure_policy(
    policies: Mapping[str, ReadModelPolicy],
    *,
    surface: str,
) -> dict[str, ReadModelPolicy]:
    """Validate one adapter-local exposure policy against canonical resource IDs."""
    from bigbrotr.services.common.read_models import (  # noqa: PLC0415
        normalize_readable_resource_policies,
    )

    return normalize_readable_resource_policies(policies, surface=cast("ReadSurface", surface))


class PublicReadAdapterConfig(BaseServiceConfig):
    """Shared config contract for protocol adapters exposing readable resources.

    The public YAML contract still uses ``read_models`` for compatibility, but
    this base model treats that field explicitly as the adapter's protocol
    exposure policy over canonical readable-resource IDs.
    """

    READ_SURFACE: ClassVar[str]
    model_config = ConfigDict(extra="forbid")

    default_page_size: int = Field(
        default=100,
        ge=1,
        le=10000,
        description="Default query limit when not specified",
    )
    max_page_size: int = Field(
        default=1000,
        ge=1,
        le=10000,
        description="Hard ceiling on query limit",
    )
    read_models: dict[str, ReadModelPolicy] = Field(
        default_factory=dict,
        description="Adapter-local protocol exposure policy keyed by public readable-resource ID",
    )

    @model_validator(mode="before")
    @classmethod
    def _require_string_field_keys(cls, data: Any) -> Any:
        return _require_string_mapping_keys(data, "config")

    @field_validator("default_page_size", "max_page_size", mode="before")
    @classmethod
    def _require_integer_page_sizes(cls, value: Any, info: ValidationInfo) -> int:
        field_name = info.field_name or "value"
        return _require_int(value, field_name)

    @field_validator("read_models", mode="before")
    @classmethod
    def _require_string_read_model_keys(cls, value: Any, info: ValidationInfo) -> Any:
        field_name = info.field_name or "value"
        return _require_string_mapping_keys(value, field_name)

    @property
    def exposure_policy(self) -> dict[str, ReadModelPolicy]:
        """Return the adapter-local protocol exposure policy."""
        return self.read_models

    @model_validator(mode="before")
    @classmethod
    def _reject_legacy_tables_key(cls, data: Any) -> Any:
        if isinstance(data, dict) and "tables" in data:
            raise ValueError("Use read_models instead of tables")
        return data

    @model_validator(mode="after")
    def _validate_page_sizes(self) -> PublicReadAdapterConfig:
        if self.default_page_size > self.max_page_size:
            msg = (
                f"default_page_size ({self.default_page_size}) "
                f"must not exceed max_page_size ({self.max_page_size})"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _validate_protocol_exposure_policy(self) -> PublicReadAdapterConfig:
        self.read_models = normalize_protocol_exposure_policy(
            self.read_models,
            surface=type(self).READ_SURFACE,
        )
        return self


class ClearnetConfig(BaseModel):
    """Configuration for clearnet (standard internet) relays.

    Direct connections without a proxy. Supports high concurrency with
    short timeouts.

    See Also:
        ``NetworkType.CLEARNET``:
            The enum member this config maps to.
    """

    enabled: bool = Field(default=True, description="Enable clearnet relay processing")
    proxy_url: str | None = Field(
        default=None, description="SOCKS5 proxy URL (None for direct connection)"
    )
    max_tasks: int = Field(default=30, ge=1, le=200, description="Maximum concurrent connections")
    timeout: float = Field(
        default=10.0, ge=1.0, le=120.0, description="Connection timeout in seconds"
    )

    @model_validator(mode="before")
    @classmethod
    def _require_string_field_keys(cls, data: Any) -> Any:
        return _require_string_mapping_keys(data, "config")

    @field_validator("max_tasks", mode="before")
    @classmethod
    def require_integer_max_tasks(cls, value: Any, info: ValidationInfo) -> int:
        field_name = info.field_name or "value"
        return _require_int(value, field_name)

    @field_validator("timeout", mode="before")
    @classmethod
    def require_numeric_timeout(cls, value: Any, info: ValidationInfo) -> int | float:
        field_name = info.field_name or "value"
        return _require_number(value, field_name)

    @field_validator("enabled", mode="before")
    @classmethod
    def require_boolean_enabled(cls, value: Any, info: ValidationInfo) -> bool:
        field_name = info.field_name or "enabled"
        return _require_bool(value, field_name)

    @field_validator("proxy_url", mode="before")
    @classmethod
    def normalize_proxy_url(cls, value: Any) -> str | None:
        return _normalize_optional_proxy_url(value)


class TorConfig(BaseModel):
    """Configuration for Tor (.onion) relays.

    Requires a SOCKS5 proxy. Lower concurrency and longer timeouts due
    to Tor network latency.

    See Also:
        ``NetworkType.TOR``:
            The enum member this config maps to.
    """

    enabled: bool = Field(default=False, description="Enable Tor relay processing")
    proxy_url: str | None = Field(
        default="socks5://tor:9050", description="SOCKS5 proxy URL for Tor"
    )
    max_tasks: int = Field(default=10, ge=1, le=200, description="Maximum concurrent connections")
    timeout: float = Field(
        default=30.0, ge=1.0, le=120.0, description="Connection timeout in seconds"
    )

    @model_validator(mode="before")
    @classmethod
    def _require_string_field_keys(cls, data: Any) -> Any:
        return _require_string_mapping_keys(data, "config")

    @field_validator("max_tasks", mode="before")
    @classmethod
    def require_integer_max_tasks(cls, value: Any, info: ValidationInfo) -> int:
        field_name = info.field_name or "value"
        return _require_int(value, field_name)

    @field_validator("timeout", mode="before")
    @classmethod
    def require_numeric_timeout(cls, value: Any, info: ValidationInfo) -> int | float:
        field_name = info.field_name or "value"
        return _require_number(value, field_name)

    @field_validator("enabled", mode="before")
    @classmethod
    def require_boolean_enabled(cls, value: Any, info: ValidationInfo) -> bool:
        field_name = info.field_name or "enabled"
        return _require_bool(value, field_name)

    @field_validator("proxy_url", mode="before")
    @classmethod
    def normalize_proxy_url(cls, value: Any) -> str | None:
        return _normalize_optional_proxy_url(value)


class I2pConfig(BaseModel):
    """Configuration for I2P (.i2p) relays.

    Requires a SOCKS5 proxy. Lowest concurrency and longest timeouts due
    to I2P network latency.

    See Also:
        ``NetworkType.I2P``:
            The enum member this config maps to.
    """

    enabled: bool = Field(default=False, description="Enable I2P relay processing")
    proxy_url: str | None = Field(
        default="socks5://i2p:4447", description="SOCKS5 proxy URL for I2P"
    )
    max_tasks: int = Field(default=5, ge=1, le=200, description="Maximum concurrent connections")
    timeout: float = Field(
        default=45.0, ge=1.0, le=120.0, description="Connection timeout in seconds"
    )

    @model_validator(mode="before")
    @classmethod
    def _require_string_field_keys(cls, data: Any) -> Any:
        return _require_string_mapping_keys(data, "config")

    @field_validator("max_tasks", mode="before")
    @classmethod
    def require_integer_max_tasks(cls, value: Any, info: ValidationInfo) -> int:
        field_name = info.field_name or "value"
        return _require_int(value, field_name)

    @field_validator("timeout", mode="before")
    @classmethod
    def require_numeric_timeout(cls, value: Any, info: ValidationInfo) -> int | float:
        field_name = info.field_name or "value"
        return _require_number(value, field_name)

    @field_validator("enabled", mode="before")
    @classmethod
    def require_boolean_enabled(cls, value: Any, info: ValidationInfo) -> bool:
        field_name = info.field_name or "enabled"
        return _require_bool(value, field_name)

    @field_validator("proxy_url", mode="before")
    @classmethod
    def normalize_proxy_url(cls, value: Any) -> str | None:
        return _normalize_optional_proxy_url(value)


class LokiConfig(BaseModel):
    """Configuration for Lokinet (.loki) relays.

    Requires a SOCKS5 proxy.

    Warning:
        Lokinet is only supported on Linux. Enabling this config on macOS
        or Windows will result in connection failures.

    See Also:
        ``NetworkType.LOKI``:
            The enum member this config maps to.
    """

    enabled: bool = Field(default=False, description="Enable Lokinet relay processing")
    proxy_url: str | None = Field(
        default="socks5://lokinet:1080", description="SOCKS5 proxy URL for Lokinet"
    )
    max_tasks: int = Field(default=5, ge=1, le=200, description="Maximum concurrent connections")
    timeout: float = Field(
        default=30.0, ge=1.0, le=120.0, description="Connection timeout in seconds"
    )

    @model_validator(mode="before")
    @classmethod
    def _require_string_field_keys(cls, data: Any) -> Any:
        return _require_string_mapping_keys(data, "config")

    @field_validator("max_tasks", mode="before")
    @classmethod
    def require_integer_max_tasks(cls, value: Any, info: ValidationInfo) -> int:
        field_name = info.field_name or "value"
        return _require_int(value, field_name)

    @field_validator("timeout", mode="before")
    @classmethod
    def require_numeric_timeout(cls, value: Any, info: ValidationInfo) -> int | float:
        field_name = info.field_name or "value"
        return _require_number(value, field_name)

    @field_validator("enabled", mode="before")
    @classmethod
    def require_boolean_enabled(cls, value: Any, info: ValidationInfo) -> bool:
        field_name = info.field_name or "enabled"
        return _require_bool(value, field_name)

    @field_validator("proxy_url", mode="before")
    @classmethod
    def normalize_proxy_url(cls, value: Any) -> str | None:
        return _normalize_optional_proxy_url(value)


# Union type for any network-specific configuration
NetworkTypeConfig = ClearnetConfig | TorConfig | I2pConfig | LokiConfig


class NetworksConfig(BaseModel):
    """Unified network configuration container for all BigBrotr services.

    Aggregates per-network settings with convenience methods for querying
    enabled state, proxy URLs, and network-specific configs. Designed to
    be embedded in service configuration models such as
    [ValidatorConfig][bigbrotr.services.validator.ValidatorConfig],
    [MonitorConfig][bigbrotr.services.monitor.MonitorConfig], and
    [SynchronizerConfig][bigbrotr.services.synchronizer.SynchronizerConfig].

    See Also:
        [NetworkSemaphoresMixin][bigbrotr.services.common.mixins.NetworkSemaphoresMixin]:
            Creates per-network ``asyncio.Semaphore`` instances from
            ``max_tasks`` values in this config.
        [NetworkType][bigbrotr.models.constants.NetworkType]: Enum used
            as lookup keys in ``get()``, ``is_enabled()``, and
            ``get_proxy_url()``.

    Examples:
        ```python
        config = NetworksConfig(tor=TorConfig(enabled=True))
        config.is_enabled(NetworkType.TOR)  # True
        config.get_proxy_url(NetworkType.TOR)  # 'socks5://tor:9050'
        config.get_enabled_networks()  # ['clearnet', 'tor']
        ```
    """

    clearnet: ClearnetConfig = Field(
        default_factory=ClearnetConfig, description="Clearnet relay settings"
    )
    tor: TorConfig = Field(default_factory=TorConfig, description="Tor relay settings")
    i2p: I2pConfig = Field(default_factory=I2pConfig, description="I2P relay settings")
    loki: LokiConfig = Field(default_factory=LokiConfig, description="Lokinet relay settings")

    @model_validator(mode="before")
    @classmethod
    def _require_string_network_field_keys(cls, data: Any) -> Any:
        return _require_string_mapping_keys(data, "config")

    def get(self, network: NetworkType) -> NetworkTypeConfig:
        """Get configuration for a specific network type.

        Args:
            network: The [NetworkType][bigbrotr.models.constants.NetworkType]
                enum value to look up.

        Returns:
            The configuration for the specified network.
            Falls back to clearnet config if network is not found.
        """
        config: NetworkTypeConfig | None = getattr(self, network.value, None)
        if config is None:
            logger.warning("no config for network=%s, falling back to clearnet", network.value)
            return self.clearnet
        return config

    def get_proxy_url(self, network: NetworkType) -> str | None:
        """Get the SOCKS5 proxy URL for a network type.

        Returns the proxy URL only if the network is enabled and has a
        configured proxy. Clearnet always returns ``None``.

        Args:
            network: The [NetworkType][bigbrotr.models.constants.NetworkType]
                enum value to look up.

        Returns:
            The SOCKS5 proxy URL if enabled and configured, ``None`` otherwise.

        Note:
            Used by [connect_relay][bigbrotr.utils.protocol.connect_relay]
            and [is_nostr_relay][bigbrotr.utils.protocol.is_nostr_relay]
            to route overlay-network connections through SOCKS5 proxies.
        """
        if network == NetworkType.CLEARNET:
            return None

        config = self.get(network)
        return config.proxy_url if config.enabled else None

    def is_enabled(self, network: NetworkType) -> bool:
        """Check if processing is enabled for a network type.

        Args:
            network: The [NetworkType][bigbrotr.models.constants.NetworkType]
                enum value to look up.

        Returns:
            True if the network is enabled, False otherwise.
        """
        return self.get(network).enabled

    def get_enabled_networks(self) -> list[NetworkType]:
        """Get a list of all enabled network types.

        Returns:
            Enabled networks as NetworkType values (order matches field definition).
        """
        return [
            NetworkType(name) for name in type(self).model_fields if getattr(self, name).enabled
        ]
