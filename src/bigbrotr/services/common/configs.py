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
    [NetworkSemaphoreMixin][bigbrotr.services.common.mixins.NetworkSemaphoreMixin]:
        Uses ``max_tasks`` to create per-network concurrency semaphores.
    [ValidatorConfig][bigbrotr.services.validator.ValidatorConfig],
    [MonitorConfig][bigbrotr.services.monitor.MonitorConfig],
    [SynchronizerConfig][bigbrotr.services.synchronizer.SynchronizerConfig]:
        Service configs that embed ``NetworkConfig``.

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

from pydantic import BaseModel, Field

from bigbrotr.models.constants import NetworkType


# =============================================================================
# Network-Specific Configuration Classes
# =============================================================================


class ClearnetConfig(BaseModel):
    """Configuration for clearnet (standard internet) relays.

    Direct connections without a proxy. Supports high concurrency with
    short timeouts.

    See Also:
        ``NetworkType.CLEARNET``:
            The enum member this config maps to.
    """

    enabled: bool = True
    proxy_url: str | None = None
    max_tasks: int = Field(default=50, ge=1, le=200)
    timeout: float = Field(default=10.0, ge=1.0, le=120.0)


class TorConfig(BaseModel):
    """Configuration for Tor (.onion) relays.

    Requires a SOCKS5 proxy. Lower concurrency and longer timeouts due
    to Tor network latency.

    See Also:
        ``NetworkType.TOR``:
            The enum member this config maps to.
    """

    enabled: bool = False
    proxy_url: str | None = "socks5://tor:9050"
    max_tasks: int = Field(default=10, ge=1, le=200)
    timeout: float = Field(default=30.0, ge=1.0, le=120.0)


class I2pConfig(BaseModel):
    """Configuration for I2P (.i2p) relays.

    Requires a SOCKS5 proxy. Lowest concurrency and longest timeouts due
    to I2P network latency.

    See Also:
        ``NetworkType.I2P``:
            The enum member this config maps to.
    """

    enabled: bool = False
    proxy_url: str | None = "socks5://i2p:4447"
    max_tasks: int = Field(default=5, ge=1, le=200)
    timeout: float = Field(default=45.0, ge=1.0, le=120.0)


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

    enabled: bool = False
    proxy_url: str | None = "socks5://lokinet:1080"
    max_tasks: int = Field(default=5, ge=1, le=200)
    timeout: float = Field(default=30.0, ge=1.0, le=120.0)


# Union type for any network-specific configuration
NetworkTypeConfig = ClearnetConfig | TorConfig | I2pConfig | LokiConfig


# =============================================================================
# Unified Network Configuration
# =============================================================================


class NetworkConfig(BaseModel):
    """Unified network configuration container for all BigBrotr services.

    Aggregates per-network settings with convenience methods for querying
    enabled state, proxy URLs, and network-specific configs. Designed to
    be embedded in service configuration models such as
    [ValidatorConfig][bigbrotr.services.validator.ValidatorConfig],
    [MonitorConfig][bigbrotr.services.monitor.MonitorConfig], and
    [SynchronizerConfig][bigbrotr.services.synchronizer.SynchronizerConfig].

    See Also:
        [NetworkSemaphoreMixin][bigbrotr.services.common.mixins.NetworkSemaphoreMixin]:
            Creates per-network ``asyncio.Semaphore`` instances from
            ``max_tasks`` values in this config.
        [NetworkType][bigbrotr.models.constants.NetworkType]: Enum used
            as lookup keys in ``get()``, ``is_enabled()``, and
            ``get_proxy_url()``.

    Examples:
        ```python
        config = NetworkConfig(tor=TorConfig(enabled=True))
        config.is_enabled(NetworkType.TOR)  # True
        config.get_proxy_url(NetworkType.TOR)  # 'socks5://tor:9050'
        config.get_enabled_networks()  # ['clearnet', 'tor']
        ```
    """

    clearnet: ClearnetConfig = Field(default_factory=ClearnetConfig)
    tor: TorConfig = Field(default_factory=TorConfig)
    i2p: I2pConfig = Field(default_factory=I2pConfig)
    loki: LokiConfig = Field(default_factory=LokiConfig)

    def get(self, network: NetworkType) -> NetworkTypeConfig:
        """Get configuration for a specific network type.

        Args:
            network: The [NetworkType][bigbrotr.models.constants.NetworkType]
                enum value to look up.

        Returns:
            The configuration for the specified network.
            Falls back to clearnet config if network is not found.
        """
        return getattr(self, network.value, self.clearnet)

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
            Used by [connect_relay][bigbrotr.utils.transport.connect_relay]
            and [is_nostr_relay][bigbrotr.utils.transport.is_nostr_relay]
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

    def get_enabled_networks(self) -> list[str]:
        """Get a list of all enabled network type names.

        Returns:
            Names of enabled networks (order matches field definition).
        """
        return [name for name in type(self).model_fields if getattr(self, name).enabled]
