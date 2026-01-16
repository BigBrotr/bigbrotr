"""Unified network configuration for all services.

Provides network-specific settings for relay connectivity:
- enabled: Whether to process relays on this network
- proxy_url: SOCKS5 proxy for overlay networks (Tor, I2P, Loki)
- max_tasks: Concurrent connection limit (for services with parallelism)
- timeout: Connection timeout in seconds

Services use what they need:
- Validator: uses all fields (enabled, proxy_url, max_tasks, timeout)
- Monitor: uses enabled, proxy_url, timeout
- Synchronizer: uses enabled, proxy_url, max_tasks
- Finder: uses enabled only
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from models.relay import NetworkType


class NetworkTypeConfig(BaseModel):
    """Unified settings for a single network type.

    Combines connectivity (enabled/proxy) with performance (concurrency/timeout).
    Services use the fields they need; unused fields have sensible defaults.
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
    """Unified network configuration for all services.

    Each network type has its own settings:
    - enabled: Whether to process relays on this network
    - proxy_url: SOCKS5 proxy for overlay networks
    - max_tasks: Concurrent connection limit
    - timeout: Connection timeout

    Example YAML:
        networks:
          clearnet:
            enabled: true
            max_tasks: 50
            timeout: 10.0
          tor:
            enabled: false  # Enable with proxy for Tor support
            proxy_url: "socks5://tor:9050"
            max_tasks: 10
            timeout: 30.0
          i2p:
            enabled: false  # Enable with proxy for I2P support
            proxy_url: "socks5://i2p:4447"
            max_tasks: 5
            timeout: 45.0
          loki:
            enabled: false  # Enable with proxy for Lokinet support
            proxy_url: "socks5://lokinet:1080"
            max_tasks: 5
            timeout: 30.0
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
        """Get config for a network type."""
        return getattr(self, network.value, self.clearnet)

    def get_proxy_url(self, network: str | NetworkType) -> str | None:
        """Get proxy URL for a network type.

        Returns proxy_url if network is enabled and has one, None otherwise.
        Clearnet always returns None (no proxy needed).
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
        """Check if a network is enabled."""
        if isinstance(network, str):
            try:
                network = NetworkType(network)
            except ValueError:
                return False

        return self.get(network).enabled

    def get_enabled_networks(self) -> list[str]:
        """Get list of enabled network names."""
        return [name for name in ["clearnet", "tor", "i2p", "loki"] if getattr(self, name).enabled]
