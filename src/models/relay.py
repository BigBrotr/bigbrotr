"""
Relay model for BigBrotr.

Provides the Relay class for representing validated Nostr relay URLs
with automatic URL normalization and network type detection.
"""

from dataclasses import dataclass
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network
from time import time
from typing import Any, ClassVar

from rfc3986 import uri_reference
from rfc3986.exceptions import UnpermittedComponentError, ValidationError
from rfc3986.validators import Validator


# Standard WebSocket ports
PORT_WS = 80
PORT_WSS = 443


@dataclass(frozen=True, slots=True)
class Relay:
    """
    Immutable representation of a Nostr relay.

    Validates and normalizes WebSocket URLs (ws:// or wss://), auto-detecting
    network type (clearnet, tor, i2p, loki). Rejects local/private addresses.

    Attributes:
        url_without_scheme: Unique identifier without scheme (e.g., "relay.example.com:8080/path").
        network: Detected network type ("clearnet", "tor", "i2p", "loki").
        discovered_at: Unix timestamp when the relay was discovered.
        scheme: URL scheme ("ws" or "wss").
        host: Hostname or IP address.
        port: Port number or None if using default (443 for wss, 80 for ws).
        path: URL path or None.

    Example:
        >>> relay = Relay("wss://relay.example.com")
        >>> relay.url
        'wss://relay.example.com'
        >>> relay.network
        'clearnet'

        >>> tor_relay = Relay("ws://abc123.onion")
        >>> tor_relay.network
        'tor'

    Raises:
        ValueError: If URL is invalid, uses unsupported scheme, or is a local address.
    """

    url_without_scheme: str  # Unique identifier (e.g., relay.example.com:8080/path)
    network: str
    discovered_at: int
    scheme: str
    host: str
    port: int | None
    path: str | None

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

    @property
    def url(self) -> str:
        """Full URL with scheme (e.g., wss://relay.example.com)."""
        return f"{self.scheme}://{self.url_without_scheme}"

    @staticmethod
    def _detect_network(host: str) -> str:
        """
        Detect the network type from a hostname.

        Analyzes the host string to determine which network it belongs to.
        Checks for overlay network TLDs first, then validates IP addresses
        against known local/private ranges, and finally validates domain format.

        Args:
            host: Hostname to analyze (e.g., "relay.example.com", "xyz.onion", "192.168.1.1")

        Returns:
            Network type string:
            - "clearnet": Standard domain or public IP address
            - "tor": .onion address (Tor hidden service)
            - "i2p": .i2p address (I2P network)
            - "loki": .loki address (Lokinet)
            - "local": Private/reserved IP or localhost (127.0.0.1, 10.x.x.x, etc.)
            - "unknown": Invalid or unrecognized format

        Examples:
            >>> Relay._detect_network("relay.example.com")
            'clearnet'
            >>> Relay._detect_network("abcdef1234567890.onion")
            'tor'
            >>> Relay._detect_network("127.0.0.1")
            'local'
            >>> Relay._detect_network("10.0.0.1")
            'local'
            >>> Relay._detect_network("")
            'unknown'
        """
        if not host:
            return "unknown"

        host = host.lower()
        host_bare = host.strip("[]")

        if host_bare.endswith(".onion"):
            return "tor"
        if host_bare.endswith(".i2p"):
            return "i2p"
        if host_bare.endswith(".loki"):
            return "loki"

        if host_bare in ("localhost", "localhost.localdomain"):
            return "local"

        try:
            ip = ip_address(host_bare)
            if any(ip in net for net in Relay._LOCAL_NETWORKS):
                return "local"
            return "clearnet"
        except ValueError:
            pass

        if "." in host_bare:
            labels = host_bare.split(".")
            for label in labels:
                if not label or label.startswith("-") or label.endswith("-"):
                    return "unknown"
            return "clearnet"

        return "unknown"

    @staticmethod
    def _parse(raw: str) -> dict[str, Any]:
        """
        Parse and normalize a relay URL.

        Args:
            raw: Raw URL string to parse.

        Returns:
            Dictionary with keys: url_without_scheme, scheme, host, port, path.

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

        scheme = uri.scheme
        port = int(uri.port) if uri.port else None

        # Normalize host (strip brackets from IPv6)
        host = uri.host.strip("[]")

        # Normalize path
        path = uri.path or ""
        while "//" in path:
            path = path.replace("//", "/")
        path = path.rstrip("/") or None

        # Format host for URL (add brackets back for IPv6)
        formatted_host = f"[{host}]" if ":" in host else host

        # Build URL without scheme
        default_port = PORT_WSS if scheme == "wss" else PORT_WS
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
        }

    def __new__(cls, raw: str, discovered_at: int | None = None) -> "Relay":
        """
        Create a new Relay instance.

        Uses __new__ instead of __init__ to support frozen dataclass immutability.
        The __init__ method is intentionally empty as all initialization happens here.

        Args:
            raw: WebSocket URL (wss:// or ws://)
            discovered_at: Unix timestamp when discovered (defaults to now)

        Returns:
            Relay instance with normalized URL and detected network type

        Raises:
            ValueError: If URL is invalid, local, or uses unknown network
        """
        parsed = cls._parse(raw)
        network = cls._detect_network(parsed["host"])

        if network == "local":
            raise ValueError("Local addresses not allowed")
        if network == "unknown":
            raise ValueError(f"Invalid host: '{parsed['host']}'")

        instance = object.__new__(cls)
        object.__setattr__(instance, "url_without_scheme", parsed["url_without_scheme"])
        object.__setattr__(instance, "network", network)
        object.__setattr__(
            instance, "discovered_at", discovered_at if discovered_at is not None else int(time())
        )
        object.__setattr__(instance, "scheme", parsed["scheme"])
        object.__setattr__(instance, "host", parsed["host"])
        object.__setattr__(instance, "port", parsed["port"])
        object.__setattr__(instance, "path", parsed["path"])
        return instance

    def __init__(self, raw: str, discovered_at: int | None = None) -> None:
        """Empty initializer; all initialization is performed in __new__ for frozen dataclass."""

    def to_db_params(self) -> tuple[str, str, int]:
        """
        Returns parameters for database insert.

        Returns:
            Tuple of (url_without_scheme, network, discovered_at)
        """
        return (self.url_without_scheme, self.network, self.discovered_at)

    @classmethod
    def from_db_params(
        cls,
        url_without_scheme: str,
        network: str,  # noqa: ARG003
        discovered_at: int,
    ) -> "Relay":
        """
        Create a Relay from database parameters by re-parsing the URL.

        Args:
            url_without_scheme: The relay URL without scheme (e.g., "relay.example.com")
            network: Network type ("clearnet", "tor", "i2p", "loki")
            discovered_at: Unix timestamp when discovered

        Returns:
            Relay instance with the provided values
        """
        return cls(f"wss://{url_without_scheme}", discovered_at)
