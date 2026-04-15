"""Shared configuration models for BigBrotr services.

Provides Pydantic models for managing per-network settings (clearnet, Tor, I2P,
Lokinet). Each network type has its own config class with sensible defaults,
allowing partial YAML overrides (e.g., setting only ``tor.enabled: true``
inherits the default ``proxy_url``).

The network type is determined by the
[NetworkType][bigbrotr.models.constants.NetworkType] enum, and the relay's
network is auto-detected from its URL scheme and hostname by the
[Relay][bigbrotr.models.relay.Relay] model.

Attributes:
    enabled: Whether to process relays on this network.
    proxy_url: SOCKS5 proxy URL for overlay networks.
    max_tasks: Maximum concurrent connections.
    timeout: Connection timeout in seconds.

See Also:
    [NetworkType][bigbrotr.models.constants.NetworkType]: Enum that
        identifies each overlay network.
    [NetworkSemaphoresMixin][bigbrotr.services.common.mixins.NetworkSemaphoresMixin]:
        Uses ``max_tasks`` to create per-network concurrency semaphores.
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
from collections.abc import Sequence

from pydantic import BaseModel, Field

from bigbrotr.models import Relay
from bigbrotr.models.constants import NetworkType


logger = logging.getLogger(__name__)


def parse_relay_list(raw: object) -> list[Relay]:
    """Parse one config value into canonical relays, skipping invalid entries."""
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


def parse_optional_relay_list(raw: object) -> list[Relay] | None:
    """Parse an optional relay list, preserving ``None`` when omitted."""
    if raw is None:
        return None
    return parse_relay_list(raw)


class ReadModelConfig(BaseModel):
    """Per-read-model access and pricing policy for API and DVM services.

    Read models default to disabled (not exposed). Only read models explicitly
    listed with ``enabled: true`` in the service YAML config are served.

    Attributes:
        enabled: Whether this read model is exposed. Disabled read models return
            404 in the API and error feedback in the DVM.
        price: Price in millisats.  ``0`` means free (no payment required).
            Used by the DVM service for NIP-90 bid/payment-required.
    """

    enabled: bool = Field(default=False, description="Whether this read model is exposed")
    price: int = Field(default=0, ge=0, description="Price in millisats (0 = free)")


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
