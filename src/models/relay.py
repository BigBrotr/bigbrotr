"""
Relay model for BigBrotr.

Provides the Relay class for representing validated Nostr relay URLs
with automatic URL normalization and network type detection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network
from time import time
from typing import Any, ClassVar, NamedTuple

from rfc3986 import uri_reference
from rfc3986.exceptions import UnpermittedComponentError, ValidationError
from rfc3986.validators import Validator


class NetworkType(StrEnum):
    """Network type constants for relay classification."""

    CLEARNET = "clearnet"
    TOR = "tor"
    I2P = "i2p"
    LOKI = "loki"
    LOCAL = "local"
    UNKNOWN = "unknown"


class RelayDbParams(NamedTuple):
    """Database parameters for Relay insert operations."""

    url: str
    network: str
    discovered_at: int


@dataclass(frozen=True, slots=True)
class Relay:
    """
    Immutable representation of a Nostr relay.

    Validates and normalizes WebSocket URLs (ws:// or wss://), auto-detecting
    network type (clearnet, tor, i2p, loki). Rejects local/private addresses.

    The scheme is enforced based on network type:
    - clearnet: wss:// (secure WebSocket)
    - tor/i2p/loki: ws:// (overlay networks handle encryption)

    Attributes:
        url: Normalized URL with scheme (e.g., "wss://relay.example.com:8080/path").
        network: Detected network type ("clearnet", "tor", "i2p", "loki").
        discovered_at: Unix timestamp when the relay was discovered.
        scheme: URL scheme ("ws" or "wss"), enforced by network type.
        host: Hostname or IP address.
        port: Port number or None if using default (443 for wss, 80 for ws).
        path: URL path or None.

    Example:
        >>> relay = Relay("ws://relay.example.com")  # clearnet gets upgraded to wss
        >>> relay.url
        'wss://relay.example.com'
        >>> relay.scheme
        'wss'

        >>> tor_relay = Relay("wss://abc123.onion")  # tor gets downgraded to ws
        >>> tor_relay.url
        'ws://abc123.onion'
        >>> tor_relay.scheme
        'ws'

    Raises:
        ValueError: If URL is invalid, uses unsupported scheme, or is a local address.
    """

    # Input fields
    raw_url: str = field(repr=False)
    discovered_at: int = field(default_factory=lambda: int(time()))

    # Computed fields (set in __post_init__)
    url: str = field(init=False)
    network: NetworkType = field(init=False)
    scheme: str = field(init=False)
    host: str = field(init=False)
    port: int | None = field(init=False)
    path: str | None = field(init=False)

    # Standard WebSocket ports
    _PORT_WS: ClassVar[int] = 80
    _PORT_WSS: ClassVar[int] = 443

    # Overlay network TLDs
    _NETWORK_TLDS: ClassVar[dict[str, NetworkType]] = {
        ".onion": NetworkType.TOR,
        ".i2p": NetworkType.I2P,
        ".loki": NetworkType.LOKI,
    }

    # Complete list of private/reserved IP networks per IANA registries
    # https://www.iana.org/assignments/iana-ipv4-special-registry/
    # https://www.iana.org/assignments/iana-ipv6-special-registry/
    _LOCAL_NETWORKS: ClassVar[list[IPv4Network | IPv6Network]] = [
        # IPv4 Private/Reserved
        ip_network("0.0.0.0/8"),  # "This host on this network" (RFC 1122)
        ip_network("10.0.0.0/8"),  # Private-Use (RFC 1918)
        ip_network("100.64.0.0/10"),  # Shared Address Space / CGNAT (RFC 6598)
        ip_network("127.0.0.0/8"),  # Loopback (RFC 1122)
        ip_network("169.254.0.0/16"),  # Link Local (RFC 3927)
        ip_network("172.16.0.0/12"),  # Private-Use (RFC 1918)
        ip_network("192.0.0.0/24"),  # IETF Protocol Assignments (RFC 6890)
        ip_network("192.0.2.0/24"),  # Documentation TEST-NET-1 (RFC 5737)
        ip_network("192.88.99.0/24"),  # 6to4 Relay Anycast (RFC 7526)
        ip_network("192.168.0.0/16"),  # Private-Use (RFC 1918)
        ip_network("198.18.0.0/15"),  # Benchmarking (RFC 2544)
        ip_network("198.51.100.0/24"),  # Documentation TEST-NET-2 (RFC 5737)
        ip_network("203.0.113.0/24"),  # Documentation TEST-NET-3 (RFC 5737)
        ip_network("224.0.0.0/4"),  # Multicast (RFC 5771)
        ip_network("240.0.0.0/4"),  # Reserved for Future Use (RFC 1112)
        ip_network("255.255.255.255/32"),  # Limited Broadcast (RFC 919)
        # IPv6 Private/Reserved
        ip_network("::1/128"),  # Loopback (RFC 4291)
        ip_network("::/128"),  # Unspecified (RFC 4291)
        ip_network("::ffff:0:0/96"),  # IPv4-mapped (RFC 4291)
        ip_network("64:ff9b::/96"),  # IPv4-IPv6 Translation (RFC 6052)
        ip_network("100::/64"),  # Discard-Only (RFC 6666)
        ip_network("2001::/32"),  # Teredo (RFC 4380)
        ip_network("2001:2::/48"),  # Benchmarking (RFC 5180)
        ip_network("2001:db8::/32"),  # Documentation (RFC 3849)
        ip_network("2001:10::/28"),  # ORCHID (RFC 4843)
        ip_network("fc00::/7"),  # Unique Local (RFC 4193)
        ip_network("fe80::/10"),  # Link-Local Unicast (RFC 4291)
        ip_network("ff00::/8"),  # Multicast (RFC 4291)
    ]

    def __post_init__(self) -> None:
        """Parse and validate the raw URL, setting computed fields."""
        # Remove null bytes (PostgreSQL rejects them in TEXT columns)
        raw = self.raw_url.replace("\x00", "") if "\x00" in self.raw_url else self.raw_url
        parsed = self._parse(raw)

        if parsed["network"] == NetworkType.LOCAL:
            raise ValueError("Local addresses not allowed")
        if parsed["network"] == NetworkType.UNKNOWN:
            raise ValueError(f"Invalid host: '{parsed['host']}'")

        # Use object.__setattr__ to bypass frozen restriction
        object.__setattr__(self, "url", f"{parsed['scheme']}://{parsed['url_without_scheme']}")
        object.__setattr__(self, "network", parsed["network"])
        object.__setattr__(self, "scheme", parsed["scheme"])
        object.__setattr__(self, "host", parsed["host"])
        object.__setattr__(self, "port", parsed["port"])
        object.__setattr__(self, "path", parsed["path"])

    @staticmethod
    def _detect_network(host: str) -> NetworkType:
        """
        Detect the network type from a hostname.

        Analyzes the host string to determine which network it belongs to.
        Checks for overlay network TLDs first, then validates IP addresses
        against known local/private ranges, and finally validates domain format.

        Args:
            host: Hostname to analyze (e.g., "relay.example.com", "xyz.onion", "192.168.1.1")

        Returns:
            NetworkType enum value:
            - CLEARNET: Standard domain or public IP address
            - TOR: .onion address (Tor hidden service)
            - I2P: .i2p address (I2P network)
            - LOKI: .loki address (Lokinet)
            - LOCAL: Private/reserved IP or localhost
            - UNKNOWN: Invalid or unrecognized format

        Examples:
            >>> Relay._detect_network("relay.example.com")
            NetworkType.CLEARNET
            >>> Relay._detect_network("abcdef1234567890.onion")
            NetworkType.TOR
            >>> Relay._detect_network("127.0.0.1")
            NetworkType.LOCAL
        """
        if not host:
            return NetworkType.UNKNOWN

        host = host.lower()
        host_bare = host.strip("[]")

        for tld, network in Relay._NETWORK_TLDS.items():
            if host_bare.endswith(tld):
                return network

        if host_bare in ("localhost", "localhost.localdomain"):
            return NetworkType.LOCAL

        try:
            ip = ip_address(host_bare)
            if any(ip in net for net in Relay._LOCAL_NETWORKS):
                return NetworkType.LOCAL
            return NetworkType.CLEARNET
        except ValueError:
            pass

        if "." in host_bare:
            labels = host_bare.split(".")
            for label in labels:
                if not label or label.startswith("-") or label.endswith("-"):
                    return NetworkType.UNKNOWN
            return NetworkType.CLEARNET

        return NetworkType.UNKNOWN

    @staticmethod
    def _parse(raw: str) -> dict[str, Any]:
        """
        Parse and normalize a relay URL.

        Args:
            raw: Raw URL string to parse.

        Returns:
            Dictionary with keys: url_without_scheme, scheme, host, port, path, network.

        Raises:
            ValueError: If URL is invalid or uses unsupported scheme.
        """
        uri = uri_reference(raw.strip()).normalize()

        validator = (
            Validator()
            .require_presence_of("scheme", "host")
            .allow_schemes("ws", "wss")
            .check_validity_of("scheme", "host", "port", "path")
        )

        try:
            validator.validate(uri)
        except UnpermittedComponentError:
            raise ValueError("Invalid scheme: must be ws or wss") from None
        except ValidationError as e:
            raise ValueError(f"Invalid URL: {e}") from None

        port = int(uri.port) if uri.port else None

        # Normalize host (strip brackets from IPv6)
        host = uri.host.strip("[]")

        # Normalize path
        path = uri.path or ""
        while "//" in path:
            path = path.replace("//", "/")
        path = path.rstrip("/") or None

        # Detect network to determine final scheme
        # - clearnet: wss:// (TLS required for public internet)
        # - overlay networks (tor/i2p/loki): ws:// (encryption handled by overlay)
        network = Relay._detect_network(host)
        scheme = "wss" if network == NetworkType.CLEARNET else "ws"

        # Format host for URL (add brackets back for IPv6)
        formatted_host = f"[{host}]" if ":" in host else host

        # Build URL without scheme, omitting default port for final scheme
        default_port = Relay._PORT_WSS if scheme == "wss" else Relay._PORT_WS
        if port and port != default_port:
            url_without_scheme = f"{formatted_host}:{port}{path or ''}"
        else:
            url_without_scheme = f"{formatted_host}{path or ''}"

        return {
            "url_without_scheme": url_without_scheme,
            "scheme": scheme,
            "host": host,
            "port": port,
            "path": path,
            "network": network,
        }

    def to_db_params(self) -> RelayDbParams:
        """
        Returns parameters for database insert.

        Returns:
            RelayDbParams with named fields: url, network, discovered_at
        """
        return RelayDbParams(
            url=self.url,
            network=self.network,
            discovered_at=self.discovered_at,
        )

    @classmethod
    def from_db_params(
        cls,
        url: str,
        network: str,  # noqa: ARG003
        discovered_at: int,
    ) -> Relay:
        """
        Create a Relay from database parameters by re-parsing the URL.

        Args:
            url: The relay URL with scheme (e.g., "wss://relay.example.com")
            network: Network type ("clearnet", "tor", "i2p", "loki") - unused, recomputed
            discovered_at: Unix timestamp when discovered

        Returns:
            Relay instance with the provided values
        """
        return cls(url, discovered_at)
