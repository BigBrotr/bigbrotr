"""Network configuration for relay connectivity."""

from __future__ import annotations

from pydantic import BaseModel, Field

from models.relay import NetworkType


class NetworkTypeConfig(BaseModel):
    """Configuration for a single network type."""

    enabled: bool = Field(default=True, description="Enable this network")
    proxy_url: str | None = Field(
        default=None, description="SOCKS5 proxy URL (for overlay networks)"
    )


class NetworkConfig(BaseModel):
    """Network configuration for relay connectivity.

    Controls which network types are enabled and their proxy settings.
    Supports clearnet, Tor (.onion), I2P (.i2p), and Lokinet (.loki) networks.
    """

    clearnet: NetworkTypeConfig = Field(
        default_factory=NetworkTypeConfig,
        description="Clearnet (regular internet) relays",
    )
    tor: NetworkTypeConfig = Field(
        default_factory=lambda: NetworkTypeConfig(
            enabled=True, proxy_url="socks5://127.0.0.1:9050"
        ),
        description="Tor proxy for .onion relays",
    )
    i2p: NetworkTypeConfig = Field(
        default_factory=lambda: NetworkTypeConfig(
            enabled=False, proxy_url="socks5://127.0.0.1:4447"
        ),
        description="I2P proxy for .i2p relays",
    )
    loki: NetworkTypeConfig = Field(
        default_factory=lambda: NetworkTypeConfig(
            enabled=False, proxy_url="socks5://127.0.0.1:1080"
        ),
        description="Lokinet proxy for .loki relays",
    )

    def get_proxy_url(self, network: str | NetworkType) -> str | None:
        """Get proxy URL for a given network type.

        Args:
            network: Network type (NetworkType enum or string)

        Returns:
            Proxy URL if network requires proxy and is enabled, None otherwise.
        """
        if isinstance(network, str):
            try:
                network = NetworkType(network)
            except ValueError:
                return None

        config_map = {
            NetworkType.CLEARNET: self.clearnet,
            NetworkType.TOR: self.tor,
            NetworkType.I2P: self.i2p,
            NetworkType.LOKI: self.loki,
        }
        config = config_map.get(network)
        if config and config.enabled and config.proxy_url:
            return config.proxy_url
        return None

    def is_network_enabled(self, network: str | NetworkType) -> bool:
        """Check if a network is enabled.

        Args:
            network: Network type (NetworkType enum or string)

        Returns:
            True if network is enabled, False otherwise.
        """
        if isinstance(network, str):
            try:
                network = NetworkType(network)
            except ValueError:
                return False

        config_map = {
            NetworkType.CLEARNET: self.clearnet,
            NetworkType.TOR: self.tor,
            NetworkType.I2P: self.i2p,
            NetworkType.LOKI: self.loki,
        }
        config = config_map.get(network)
        return config.enabled if config else False
