"""Unified network configuration for all BigBrotr services.

This module provides Pydantic configuration models for managing network-specific
settings across different relay network types (clearnet, Tor, I2P, Lokinet).

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

Service Usage:
    - Validator: Uses all fields (enabled, proxy_url, max_tasks, timeout)
    - Monitor: Uses enabled, proxy_url, timeout
    - Synchronizer: Uses enabled, proxy_url, max_tasks
    - Finder: Uses enabled only

Example YAML Configuration:
    networks:
      clearnet:
        enabled: true
        max_tasks: 50
        timeout: 10.0
      tor:
        enabled: true
        proxy_url: "socks5://tor:9050"
        max_tasks: 10
        timeout: 30.0
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from models.relay import NetworkType


class NetworkTypeConfig(BaseModel):
    """Configuration settings for a single network type.

    This model combines connectivity settings (enabled/proxy) with performance
    tuning parameters (concurrency/timeout). Services use only the fields
    they need; all fields have sensible defaults.

    Attributes:
        enabled: Whether processing is enabled for relays on this network.
            Disabled networks are skipped during relay discovery and validation.
        proxy_url: SOCKS5 proxy URL for overlay networks. Required for Tor,
            I2P, and Lokinet. Format: "socks5://host:port"
        max_tasks: Maximum concurrent connections allowed. Higher values
            increase throughput but may trigger rate limiting.
        timeout: Connection timeout in seconds. Overlay networks typically
            need longer timeouts (30-45s) than clearnet (10s).

    Example:
        >>> config = NetworkTypeConfig(
        ...     enabled=True,
        ...     proxy_url="socks5://127.0.0.1:9050",
        ...     max_tasks=10,
        ...     timeout=30.0,
        ... )
    """

    enabled: bool = Field(
        default=True,
        description="Enable processing for this network",
    )
    proxy_url: str | None = Field(
        default=None,
        description="SOCKS5 proxy URL (required for overlay networks)",
    )
    max_tasks: int = Field(
        default=10,
        ge=1,
        le=200,
        description="Maximum concurrent connections (for parallel services)",
    )
    timeout: float = Field(
        default=10.0,
        ge=1.0,
        le=120.0,
        description="Connection timeout in seconds",
    )


class NetworkConfig(BaseModel):
    """Unified network configuration container for all BigBrotr services.

    This model aggregates per-network settings into a single configuration
    object. It provides convenience methods for querying network settings
    and is designed to be embedded in service configuration models.

    Attributes:
        clearnet: Settings for standard internet relays. Default: enabled
            with high concurrency (50 tasks) and short timeout (10s).
        tor: Settings for Tor .onion relays. Default: disabled, requires
            SOCKS5 proxy at socks5://tor:9050.
        i2p: Settings for I2P .i2p relays. Default: disabled, requires
            SOCKS5 proxy at socks5://i2p:4447.
        loki: Settings for Lokinet .loki relays. Default: disabled, requires
            SOCKS5 proxy at socks5://lokinet:1080.

    Example:
        >>> config = NetworkConfig(
        ...     clearnet=NetworkTypeConfig(enabled=True, max_tasks=100),
        ...     tor=NetworkTypeConfig(enabled=True, proxy_url="socks5://tor:9050"),
        ... )
        >>> config.is_enabled(NetworkType.TOR)
        True
        >>> config.get_proxy_url(NetworkType.TOR)
        'socks5://tor:9050'
    """

    clearnet: NetworkTypeConfig = Field(
        default_factory=lambda: NetworkTypeConfig(
            enabled=True,
            proxy_url=None,
            max_tasks=50,
            timeout=10.0,
        ),
        description="Clearnet relays (fast, high concurrency)",
    )
    tor: NetworkTypeConfig = Field(
        default_factory=lambda: NetworkTypeConfig(
            enabled=False,
            proxy_url="socks5://tor:9050",
            max_tasks=10,
            timeout=30.0,
        ),
        description="Tor .onion relays (slower, needs proxy)",
    )
    i2p: NetworkTypeConfig = Field(
        default_factory=lambda: NetworkTypeConfig(
            enabled=False,
            proxy_url="socks5://i2p:4447",
            max_tasks=5,
            timeout=45.0,
        ),
        description="I2P .i2p relays (slowest, needs proxy)",
    )
    loki: NetworkTypeConfig = Field(
        default_factory=lambda: NetworkTypeConfig(
            enabled=False,
            proxy_url="socks5://lokinet:1080",
            max_tasks=5,
            timeout=30.0,
        ),
        description="Lokinet .loki relays (needs proxy)",
    )

    def get(self, network: NetworkType) -> NetworkTypeConfig:
        """Get configuration for a specific network type.

        Args:
            network: The NetworkType enum value to look up.

        Returns:
            NetworkTypeConfig: The configuration for the specified network.
                Falls back to clearnet config if network is not found.
        """
        return getattr(self, network.value, self.clearnet)

    def get_proxy_url(self, network: str | NetworkType) -> str | None:
        """Get the SOCKS5 proxy URL for a network type.

        Returns the proxy URL only if the network is enabled and has a
        configured proxy. Clearnet always returns None since it doesn't
        require a proxy.

        Args:
            network: Network type as string (e.g., "tor") or NetworkType enum.

        Returns:
            str | None: The SOCKS5 proxy URL if the network is enabled and
                has a proxy configured, None otherwise.
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
            network: Network type as string (e.g., "tor") or NetworkType enum.

        Returns:
            bool: True if the network is enabled, False otherwise.
                Returns False for invalid network type strings.
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
            list[str]: Names of enabled networks (e.g., ["clearnet", "tor"]).
                Order is always: clearnet, tor, i2p, loki (if enabled).
        """
        return [name for name in ["clearnet", "tor", "i2p", "loki"] if getattr(self, name).enabled]
