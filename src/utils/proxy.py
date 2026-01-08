"""Proxy configuration for overlay networks."""

from __future__ import annotations

from pydantic import BaseModel, Field

from models.relay import NetworkType


class NetworkProxyConfig(BaseModel):
    """Configuration for a single overlay network proxy."""

    enabled: bool = Field(default=False, description="Enable this proxy")
    proxy_url: str = Field(default="", description="SOCKS5 proxy URL (e.g., socks5://host:port)")


class ProxyConfig(BaseModel):
    """Overlay network proxy configuration for hidden relay support.

    Supports Tor (.onion), I2P (.i2p), and Lokinet (.loki) networks.
    Each network requires its own SOCKS5 proxy for connectivity.
    """

    tor: NetworkProxyConfig = Field(
        default_factory=lambda: NetworkProxyConfig(
            enabled=True, proxy_url="socks5://127.0.0.1:9050"
        ),
        description="Tor proxy for .onion relays",
    )
    i2p: NetworkProxyConfig = Field(
        default_factory=lambda: NetworkProxyConfig(
            enabled=False, proxy_url="socks5://127.0.0.1:4447"
        ),
        description="I2P proxy for .i2p relays",
    )
    loki: NetworkProxyConfig = Field(
        default_factory=lambda: NetworkProxyConfig(
            enabled=False, proxy_url="socks5://127.0.0.1:1080"
        ),
        description="Lokinet proxy for .loki relays",
    )

    def get_proxy_url(self, network: str | NetworkType) -> str | None:
        """Get proxy URL for a given network type.

        Args:
            network: Network type (NetworkType.TOR, NetworkType.I2P, NetworkType.LOKI)

        Returns:
            Proxy URL if network is supported and enabled, None otherwise.
        """
        if isinstance(network, str):
            try:
                network = NetworkType(network)
            except ValueError:
                return None
        config_map = {
            NetworkType.TOR: self.tor,
            NetworkType.I2P: self.i2p,
            NetworkType.LOKI: self.loki,
        }
        config = config_map.get(network)
        if config and config.enabled and config.proxy_url:
            return config.proxy_url
        return None

    def is_network_enabled(self, network: str | NetworkType) -> bool:
        """Check if a network proxy is enabled.

        Args:
            network: Network type (NetworkType.TOR, NetworkType.I2P, NetworkType.LOKI)

        Returns:
            True if network proxy is enabled, False otherwise.
        """
        if isinstance(network, str):
            try:
                network = NetworkType(network)
            except ValueError:
                return False
        config_map = {
            NetworkType.TOR: self.tor,
            NetworkType.I2P: self.i2p,
            NetworkType.LOKI: self.loki,
        }
        config = config_map.get(network)
        return config.enabled if config else False
