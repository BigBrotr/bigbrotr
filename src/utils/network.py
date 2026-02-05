"""Unified network configuration for all BigBrotr services.

This module provides Pydantic configuration models for managing network-specific
settings across different relay network types (clearnet, Tor, I2P, Lokinet).

Each network type has its own configuration class with appropriate defaults,
allowing partial YAML overrides to work correctly (e.g., setting only
`tor.enabled: true` inherits the default `proxy_url`).

Network Types:
    - clearnet: Standard internet relays (wss://example.com)
    - tor: Tor hidden service relays (.onion addresses)
    - i2p: I2P network relays (.i2p addresses)
    - loki: Lokinet relays (.loki addresses)

Configuration Fields:
    - enabled: Whether to process relays on this network
    - proxy_url: SOCKS5 proxy for overlay networks (Tor, I2P, Loki)
    - max_tasks: Concurrent connection limit (for parallel services)
    - timeout: Connection timeout in seconds

Example YAML Configuration:
    networks:
      clearnet:
        enabled: true
        max_tasks: 100       # Override only max_tasks
      tor:
        enabled: true        # Override only enabled, inherits proxy_url default
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class NetworkType(StrEnum):
    """Network type constants for relay classification.

    Used to categorize relays by their network connectivity:
    - CLEARNET: Standard internet (requires TLS via wss://)
    - TOR: Tor hidden services (.onion addresses, ws://)
    - I2P: I2P network (.i2p addresses, ws://)
    - LOKI: Lokinet (.loki addresses, ws://)
    - LOCAL: Private/reserved addresses (rejected)
    - UNKNOWN: Invalid or unrecognized format (rejected)
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

    Clearnet relays are accessed directly without a proxy. They typically
    support high concurrency and have short timeouts.

    Defaults:
        enabled: True
        proxy_url: None (no proxy needed)
        max_tasks: 50 (high concurrency)
        timeout: 10.0s (short timeout)
    """

    enabled: bool = True
    proxy_url: str | None = None
    max_tasks: int = Field(default=50, ge=1, le=200)
    timeout: float = Field(default=10.0, ge=1.0, le=120.0)


class TorConfig(BaseModel):
    """Configuration for Tor (.onion) relays.

    Tor relays require a SOCKS5 proxy to access the Tor network. They have
    lower concurrency limits and longer timeouts due to network latency.

    Defaults:
        enabled: False
        proxy_url: socks5://tor:9050
        max_tasks: 10 (lower concurrency)
        timeout: 30.0s (longer timeout)
    """

    enabled: bool = False
    proxy_url: str | None = "socks5://tor:9050"
    max_tasks: int = Field(default=10, ge=1, le=200)
    timeout: float = Field(default=30.0, ge=1.0, le=120.0)


class I2pConfig(BaseModel):
    """Configuration for I2P (.i2p) relays.

    I2P relays require a SOCKS5 proxy to access the I2P network. They have
    the lowest concurrency limits and longest timeouts due to network latency.

    Defaults:
        enabled: False
        proxy_url: socks5://i2p:4447
        max_tasks: 5 (lowest concurrency)
        timeout: 45.0s (longest timeout)
    """

    enabled: bool = False
    proxy_url: str | None = "socks5://i2p:4447"
    max_tasks: int = Field(default=5, ge=1, le=200)
    timeout: float = Field(default=45.0, ge=1.0, le=120.0)


class LokiConfig(BaseModel):
    """Configuration for Lokinet (.loki) relays.

    Lokinet relays require a SOCKS5 proxy to access the Lokinet network.
    Note: Lokinet is only supported on Linux.

    Defaults:
        enabled: False
        proxy_url: socks5://lokinet:1080
        max_tasks: 5 (lower concurrency)
        timeout: 30.0s (longer timeout)
    """

    enabled: bool = False
    proxy_url: str | None = "socks5://lokinet:1080"
    max_tasks: int = Field(default=5, ge=1, le=200)
    timeout: float = Field(default=30.0, ge=1.0, le=120.0)


# Type alias for any network-specific config (for type hints)
NetworkTypeConfig = ClearnetConfig | TorConfig | I2pConfig | LokiConfig


# =============================================================================
# Unified Network Configuration
# =============================================================================


class NetworkConfig(BaseModel):
    """Unified network configuration container for all BigBrotr services.

    This model aggregates per-network settings into a single configuration
    object. It provides convenience methods for querying network settings
    and is designed to be embedded in service configuration models.

    Each network type uses its own configuration class with appropriate defaults,
    allowing partial YAML overrides to work correctly.

    Attributes:
        clearnet: Settings for standard internet relays.
        tor: Settings for Tor .onion relays.
        i2p: Settings for I2P .i2p relays.
        loki: Settings for Lokinet .loki relays.

    Example:
        >>> config = NetworkConfig(
        ...     clearnet=ClearnetConfig(max_tasks=100),
        ...     tor=TorConfig(enabled=True),  # Inherits proxy_url default
        ... )
        >>> config.is_enabled(NetworkType.TOR)
        True
        >>> config.get_proxy_url(NetworkType.TOR)
        'socks5://tor:9050'
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
