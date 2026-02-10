"""
Validated Nostr relay URL with network type detection.

Parses, normalizes, and validates WebSocket relay URLs (``ws://`` or ``wss://``),
automatically detecting the network type (clearnet, Tor, I2P, Lokinet) and
enforcing the correct scheme for each network. Local and private IP addresses
are rejected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network
from time import time
from typing import Any, ClassVar, NamedTuple

from rfc3986 import uri_reference
from rfc3986.exceptions import UnpermittedComponentError, ValidationError
from rfc3986.validators import Validator

from .constants import NetworkType


class RelayDbParams(NamedTuple):
    """Positional parameters for the relay database insert procedure."""

    url: str
    network: str
    discovered_at: int


@dataclass(frozen=True, slots=True)
class Relay:
    """Immutable representation of a Nostr relay.

    Validates and normalizes a WebSocket URL on construction, detecting the
    network type from the hostname. The scheme is enforced per network:

    * **clearnet** -- ``wss://`` (TLS required on the public internet)
    * **tor / i2p / loki** -- ``ws://`` (encryption handled by the overlay)

    Attributes:
        url: Fully normalized URL including scheme.
        network: Detected ``NetworkType`` enum value.
        scheme: URL scheme (``ws`` or ``wss``).
        host: Hostname or IP address (brackets stripped for IPv6).
        port: Explicit port number, or ``None`` when using the default.
        path: URL path component, or ``None``.
        discovered_at: Unix timestamp when the relay was first discovered.

    Raises:
        ValueError: If the URL is malformed, uses an unsupported scheme,
            resolves to a local/private address, or contains null bytes.

    Examples:
        ```python
        relay = Relay("wss://relay.damus.io")
        relay.url       # 'wss://relay.damus.io'
        relay.network   # NetworkType.CLEARNET
        relay.scheme    # 'wss'
        relay.to_db_params()
        # RelayDbParams(url='wss://relay.damus.io', network='clearnet', ...)
        ```

        Overlay networks automatically use `ws://`:

        ```python
        tor_relay = Relay("wss://abc123.onion")
        tor_relay.scheme    # 'ws'
        tor_relay.network   # NetworkType.TOR
        ```
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
    _db_params: RelayDbParams | None = field(
        default=None, init=False, repr=False, compare=False, hash=False
    )

    # Standard default ports for WebSocket schemes
    _PORT_WS: ClassVar[int] = 80
    _PORT_WSS: ClassVar[int] = 443

    # Overlay network TLD-to-NetworkType mapping
    _NETWORK_TLDS: ClassVar[dict[str, NetworkType]] = {
        ".onion": NetworkType.TOR,
        ".i2p": NetworkType.I2P,
        ".loki": NetworkType.LOKI,
    }

    # IANA private/reserved IP ranges used to reject local addresses.
    # References:
    #   https://www.iana.org/assignments/iana-ipv4-special-registry/
    #   https://www.iana.org/assignments/iana-ipv6-special-registry/
    _LOCAL_NETWORKS: ClassVar[list[IPv4Network | IPv6Network]] = [
        # IPv4
        ip_network("0.0.0.0/8"),
        ip_network("10.0.0.0/8"),
        ip_network("100.64.0.0/10"),
        ip_network("127.0.0.0/8"),
        ip_network("169.254.0.0/16"),
        ip_network("172.16.0.0/12"),
        ip_network("192.0.0.0/24"),
        ip_network("192.0.2.0/24"),
        ip_network("192.88.99.0/24"),
        ip_network("192.168.0.0/16"),
        ip_network("198.18.0.0/15"),
        ip_network("198.51.100.0/24"),
        ip_network("203.0.113.0/24"),
        ip_network("224.0.0.0/4"),
        ip_network("240.0.0.0/4"),
        ip_network("255.255.255.255/32"),
        # IPv6
        ip_network("::1/128"),
        ip_network("::/128"),
        ip_network("::ffff:0:0/96"),
        ip_network("64:ff9b::/96"),
        ip_network("100::/64"),
        ip_network("2001::/32"),
        ip_network("2001:2::/48"),
        ip_network("2001:db8::/32"),
        ip_network("2001:10::/28"),
        ip_network("fc00::/7"),
        ip_network("fe80::/10"),
        ip_network("ff00::/8"),
    ]

    def __post_init__(self) -> None:
        """Parse and validate the raw URL, populating all computed fields.

        Raises:
            ValueError: If the URL is invalid, local, or contains null bytes.
        """
        if "\x00" in self.raw_url:
            raise ValueError("Relay URL contains null bytes")

        parsed = self._parse(self.raw_url)

        if parsed["network"] == NetworkType.LOCAL:
            raise ValueError("Local addresses not allowed")
        if parsed["network"] == NetworkType.UNKNOWN:
            raise ValueError(f"Invalid host: '{parsed['host']}'")

        # Bypass frozen restriction to set computed fields
        object.__setattr__(self, "url", f"{parsed['scheme']}://{parsed['url_without_scheme']}")
        object.__setattr__(self, "network", parsed["network"])
        object.__setattr__(self, "scheme", parsed["scheme"])
        object.__setattr__(self, "host", parsed["host"])
        object.__setattr__(self, "port", parsed["port"])
        object.__setattr__(self, "path", parsed["path"])

        # Compute and cache DB params at creation time (fail-fast validation).
        # object.__setattr__ is required because the dataclass is frozen.
        object.__setattr__(self, "_db_params", self._compute_db_params())

    @staticmethod
    def _detect_network(host: str) -> NetworkType:
        """Classify a hostname into a network type.

        Checks overlay network TLDs first, then tests whether the host
        is a known local/private IP, and finally validates standard
        domain name format.

        Args:
            host: Hostname or IP address string to classify.

        Returns:
            The detected NetworkType. Returns ``UNKNOWN`` for empty or
            invalid hostnames, and ``LOCAL`` for private/reserved IPs.
        """
        if not host:
            return NetworkType.UNKNOWN

        host_bare = host.lower().strip("[]")

        for tld, network in Relay._NETWORK_TLDS.items():
            if host_bare.endswith(tld):
                return network

        if host_bare in ("localhost", "localhost.localdomain"):
            return NetworkType.LOCAL

        try:
            ip = ip_address(host_bare)
            is_local = any(ip in net for net in Relay._LOCAL_NETWORKS)
            return NetworkType.LOCAL if is_local else NetworkType.CLEARNET
        except ValueError:
            pass

        if "." not in host_bare:
            return NetworkType.UNKNOWN

        labels = host_bare.split(".")
        valid = all(
            label and not label.startswith("-") and not label.endswith("-") for label in labels
        )
        return NetworkType.CLEARNET if valid else NetworkType.UNKNOWN

    @staticmethod
    def _parse(raw: str) -> dict[str, Any]:
        """Parse and normalize a raw relay URL string.

        Validates the URI structure using RFC 3986, detects the network
        type, enforces the correct WebSocket scheme, normalizes the path,
        and strips default ports.

        Args:
            raw: Raw URL string (e.g., ``"ws://relay.example.com:8080/path"``).

        Returns:
            Dictionary containing ``url_without_scheme``, ``scheme``,
            ``host``, ``port``, ``path``, and ``network``.

        Raises:
            ValueError: If the scheme is not ``ws``/``wss`` or the URI is invalid.
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

        # Relay URLs must not contain query strings or fragments
        if uri.query:
            raise ValueError(f"Relay URL must not contain a query string: ?{uri.query}")
        if uri.fragment:
            raise ValueError(f"Relay URL must not contain a fragment: #{uri.fragment}")

        port = int(uri.port) if uri.port else None
        host = uri.host.strip("[]")

        # Collapse duplicate slashes and strip trailing slash
        path = uri.path or ""
        while "//" in path:
            path = path.replace("//", "/")
        path = path.rstrip("/") or None

        # Clearnet requires TLS; overlay networks handle encryption themselves
        network = Relay._detect_network(host)
        scheme = "wss" if network == NetworkType.CLEARNET else "ws"

        # Re-bracket IPv6 addresses for the final URL
        formatted_host = f"[{host}]" if ":" in host else host

        # Omit the port when it matches the default for the scheme
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
        """Return cached positional parameters for the database insert procedure.

        The result is computed once during construction and cached for the
        lifetime of the (frozen) instance, avoiding repeated network name
        conversions.

        Returns:
            RelayDbParams with the normalized URL, network name, and
            discovery timestamp.
        """
        assert self._db_params is not None  # noqa: S101  # Always set in __post_init__
        return self._db_params

    def _compute_db_params(self) -> RelayDbParams:
        """Compute positional parameters for the database insert procedure.

        Called once during ``__post_init__`` to populate the ``_db_params``
        cache. All subsequent access goes through ``to_db_params()``.

        Returns:
            RelayDbParams with the normalized URL, network name, and
            discovery timestamp.
        """
        return RelayDbParams(
            url=self.url,
            network=self.network,
            discovered_at=self.discovered_at,
        )

    @classmethod
    def from_db_params(cls, params: RelayDbParams) -> Relay:
        """Reconstruct a Relay from database parameters.

        The URL is re-parsed and re-validated; the ``network`` field in
        *params* is not used directly because it is recomputed from the URL.

        Args:
            params: Database row values previously produced by ``to_db_params()``.

        Returns:
            A new Relay instance.
        """
        return cls(params.url, params.discovered_at)
