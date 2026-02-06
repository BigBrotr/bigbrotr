"""Unified network configuration for all BigBrotr services.

Provides Pydantic models for managing per-network settings (clearnet, Tor, I2P,
Lokinet). Each network type has its own config class with sensible defaults,
allowing partial YAML overrides (e.g., setting only ``tor.enabled: true``
inherits the default ``proxy_url``).

Per-network config fields:
    - ``enabled``: Whether to process relays on this network.
    - ``proxy_url``: SOCKS5 proxy URL for overlay networks.
    - ``max_tasks``: Maximum concurrent connections.
    - ``timeout``: Connection timeout in seconds.

Example YAML::

    networks:
      clearnet:
        enabled: true
        max_tasks: 100
      tor:
        enabled: true  # Inherits default proxy_url
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class NetworkType(StrEnum):
    """Network type enum for relay classification.

    Values: CLEARNET (wss://), TOR (.onion), I2P (.i2p), LOKI (.loki),
    LOCAL (private/rejected), UNKNOWN (invalid/rejected).
    """

    CLEARNET = "clearnet"
    TOR = "tor"
    I2P = "i2p"
    LOKI = "loki"
    LOCAL = "local"
    UNKNOWN = "unknown"


# =============================================================================
# Network-Specific Configuration Classes
# =============================================================================


class ClearnetConfig(BaseModel):
    """Configuration for clearnet (standard internet) relays.

    Direct connections without a proxy. Supports high concurrency with
    short timeouts.
    """

    enabled: bool = True
    proxy_url: str | None = None
    max_tasks: int = Field(default=50, ge=1, le=200)
    timeout: float = Field(default=10.0, ge=1.0, le=120.0)


class TorConfig(BaseModel):
    """Configuration for Tor (.onion) relays.

    Requires a SOCKS5 proxy. Lower concurrency and longer timeouts due
    to Tor network latency.
    """

    enabled: bool = False
    proxy_url: str | None = "socks5://tor:9050"
    max_tasks: int = Field(default=10, ge=1, le=200)
    timeout: float = Field(default=30.0, ge=1.0, le=120.0)


class I2pConfig(BaseModel):
    """Configuration for I2P (.i2p) relays.

    Requires a SOCKS5 proxy. Lowest concurrency and longest timeouts due
    to I2P network latency.
    """

    enabled: bool = False
    proxy_url: str | None = "socks5://i2p:4447"
    max_tasks: int = Field(default=5, ge=1, le=200)
    timeout: float = Field(default=45.0, ge=1.0, le=120.0)


class LokiConfig(BaseModel):
    """Configuration for Lokinet (.loki) relays.

    Requires a SOCKS5 proxy. Note: Lokinet is only supported on Linux.
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
    be embedded in service configuration models.

    Example::

        config = NetworkConfig(tor=TorConfig(enabled=True))
        config.is_enabled(NetworkType.TOR)  # True
        config.get_proxy_url(NetworkType.TOR)  # 'socks5://tor:9050'
        config.get_enabled_networks()  # ['clearnet', 'tor']
    """

    clearnet: ClearnetConfig = Field(default_factory=ClearnetConfig)
    tor: TorConfig = Field(default_factory=TorConfig)
    i2p: I2pConfig = Field(default_factory=I2pConfig)
    loki: LokiConfig = Field(default_factory=LokiConfig)

    def get(self, network: NetworkType) -> NetworkTypeConfig:
        """Get configuration for a specific network type.

        Args:
            network: The NetworkType enum value to look up.

        Returns:
            The configuration for the specified network.
            Falls back to clearnet config if network is not found.
        """
        return getattr(self, network.value, self.clearnet)

    def get_proxy_url(self, network: str | NetworkType) -> str | None:
        """Get the SOCKS5 proxy URL for a network type.

        Returns the proxy URL only if the network is enabled and has a
        configured proxy. Clearnet always returns None.

        Args:
            network: Network type as string or NetworkType enum.

        Returns:
            The SOCKS5 proxy URL if enabled and configured, None otherwise.
        """
        if isinstance(network, str):
            try:
                network = NetworkType(network)
            except ValueError:
                return None

        if network == NetworkType.CLEARNET:
            return None

        config = self.get(network)
        return config.proxy_url if config.enabled else None

    def is_enabled(self, network: str | NetworkType) -> bool:
        """Check if processing is enabled for a network type.

        Args:
            network: Network type as string or NetworkType enum.

        Returns:
            True if the network is enabled, False otherwise.
        """
        if isinstance(network, str):
            try:
                network = NetworkType(network)
            except ValueError:
                return False

        return self.get(network).enabled

    def get_enabled_networks(self) -> list[str]:
        """Get a list of all enabled network type names.

        Returns:
            Names of enabled networks (order matches field definition).
        """
        return [name for name in type(self).model_fields if getattr(self, name).enabled]
