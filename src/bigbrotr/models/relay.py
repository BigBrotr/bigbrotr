"""
Validated Nostr relay URL with network type detection.

Parses, normalizes, and validates WebSocket relay URLs (``ws://`` or ``wss://``),
automatically detecting the [NetworkType][bigbrotr.models.constants.NetworkType]
(clearnet, Tor, I2P, Lokinet) and enforcing the correct scheme for each network.
Local and private IP addresses are rejected.

See Also:
    [bigbrotr.models.constants][]: Defines the
        [NetworkType][bigbrotr.models.constants.NetworkType] enum used for classification.
    [bigbrotr.models.event_relay][]: Links a [Relay][bigbrotr.models.relay.Relay] to an
        [Event][bigbrotr.models.event.Event] via the ``event_relay`` junction table.
    [bigbrotr.models.relay_metadata][]: Links a [Relay][bigbrotr.models.relay.Relay] to a
        [Metadata][bigbrotr.models.metadata.Metadata] record via the ``relay_metadata``
        junction table.
    [bigbrotr.utils.transport][]: Uses [Relay][bigbrotr.models.relay.Relay] URLs for
        WebSocket connectivity checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network
from time import time
from typing import Any, NamedTuple
from urllib.parse import unquote

from rfc3986 import uri_reference
from rfc3986.exceptions import UnpermittedComponentError, ValidationError
from rfc3986.validators import Validator

from ._validation import validate_str_no_null, validate_timestamp
from .constants import NetworkType


# RFC 3986 unreserved characters plus ":" (allowed in pchar).
# Used to validate individual path segments after percent-decoding and splitting on "/".
_PATH_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~:")

# Characters that may appear at the start or end of a path segment.
# Non-alphanumeric unreserved chars (-, ., _, ~) and ":" are only valid mid-segment.
_PATH_BOUNDARY_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")

_PORT_WS = 80
_PORT_WSS = 443
_MAX_URL_LENGTH = 2048

_NETWORK_TLDS: dict[str, NetworkType] = {
    ".onion": NetworkType.TOR,
    ".i2p": NetworkType.I2P,
    ".loki": NetworkType.LOKI,
}

# IANA private/reserved IP ranges used to reject local addresses.
# References:
#   https://www.iana.org/assignments/iana-ipv4-special-registry/
#   https://www.iana.org/assignments/iana-ipv6-special-registry/
_LOCAL_NETWORKS: list[IPv4Network | IPv6Network] = [
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


def _detect_network(host: str) -> NetworkType:
    """Classify a hostname into a network type.

    Checks overlay network TLDs first (``.onion``, ``.i2p``, ``.loki``),
    then tests whether the host is a known local/private IP against the
    IANA special-purpose registries, and finally validates standard
    domain name format.

    Args:
        host: Hostname or IP address string to classify.

    Returns:
        The detected [NetworkType][bigbrotr.models.constants.NetworkType].
        Returns ``UNKNOWN`` for empty or invalid hostnames, and ``LOCAL``
        for private/reserved IPs.
    """
    if not host:
        return NetworkType.UNKNOWN

    host_bare = host.lower().strip("[]")

    for tld, network in _NETWORK_TLDS.items():
        if host_bare.endswith(tld):
            return network

    if host_bare in ("localhost", "localhost.localdomain"):
        return NetworkType.LOCAL

    try:
        ip = ip_address(host_bare)
        is_local = any(ip in net for net in _LOCAL_NETWORKS)
        return NetworkType.LOCAL if is_local else NetworkType.CLEARNET
    except ValueError:
        pass

    if "." not in host_bare:
        return NetworkType.UNKNOWN

    labels = host_bare.split(".")
    valid = all(label and not label.startswith("-") and not label.endswith("-") for label in labels)
    return NetworkType.CLEARNET if valid else NetworkType.UNKNOWN


class RelayDbParams(NamedTuple):
    """Positional parameters for the relay database insert procedure.

    Produced by [Relay.to_db_params()][bigbrotr.models.relay.Relay.to_db_params]
    and consumed by the ``relay_insert`` stored procedure in PostgreSQL.

    Attributes:
        url: Fully normalized WebSocket URL including scheme.
        network: Network type string (e.g., ``"clearnet"``, ``"tor"``).
        discovered_at: Unix timestamp when the relay was first discovered.

    See Also:
        [Relay][bigbrotr.models.relay.Relay]: The model that produces these parameters.
    """

    url: str
    network: str
    discovered_at: int


@dataclass(frozen=True, slots=True)
class Relay:
    """Immutable representation of a Nostr relay.

    Accepts only URLs already in canonical form.  If the input may be
    dirty (from Nostr events, relay lists, external APIs), pass it through
    [sanitize_relay_url][bigbrotr.models.relay.sanitize_relay_url] first.

    The canonical form enforces:

    * **scheme** -- ``wss://`` for clearnet, ``ws://`` for overlay networks
    * **no query string or fragment**
    * **no garbage path** (control characters, whitespace, embedded URI schemes)
    * **default ports omitted** (443 for ``wss``, 80 for ``ws``)
    * **lowercase host**, collapsed path slashes, no trailing slash

    Attributes:
        url: Canonical normalized URL (init field and primary identity).
        network: Detected [NetworkType][bigbrotr.models.constants.NetworkType] enum value.
        scheme: URL scheme (``ws`` or ``wss``).
        host: Hostname or IP address (brackets stripped for IPv6).
        port: Explicit port number, or ``None`` when using the default.
        path: URL path component, or ``None``.
        discovered_at: Unix timestamp when the relay was first discovered.

    Raises:
        ValueError: If the URL is not in canonical form, malformed,
            uses an unsupported scheme, resolves to a local/private address,
            or contains null bytes.

    Examples:
        ```python
        relay = Relay("wss://relay.damus.io")
        relay.url       # 'wss://relay.damus.io'
        relay.network   # NetworkType.CLEARNET
        relay.scheme    # 'wss'
        relay.to_db_params()
        # RelayDbParams(url='wss://relay.damus.io', network='clearnet', ...)
        ```

        For untrusted input, sanitize first:

        ```python
        from bigbrotr.models.relay import sanitize_relay_url

        dirty = "ws://Relay.Example.Com:443/path?key=val#frag"
        clean = sanitize_relay_url(dirty)  # 'wss://relay.example.com/path'
        relay = Relay(clean)
        ```

    Note:
        Computed fields are set via ``object.__setattr__`` in ``__post_init__``
        because the dataclass is frozen. This is the standard workaround and is
        safe because it runs during ``__init__`` before the instance is exposed.

    See Also:
        [sanitize_relay_url][bigbrotr.models.relay.sanitize_relay_url]: Pre-processor
            for untrusted relay URLs.
        [NetworkType][bigbrotr.models.constants.NetworkType]: Enum of supported network types.
        [RelayDbParams][bigbrotr.models.relay.RelayDbParams]: Database parameter container
            produced by [to_db_params()][bigbrotr.models.relay.Relay.to_db_params].
        [RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata]: Junction linking
            a relay to a [Metadata][bigbrotr.models.metadata.Metadata] record.
        [EventRelay][bigbrotr.models.event_relay.EventRelay]: Junction linking a relay
            to an [Event][bigbrotr.models.event.Event].
    """

    url: str
    discovered_at: int = field(default_factory=lambda: int(time()))

    network: NetworkType = field(init=False)
    scheme: str = field(init=False)
    host: str = field(init=False)
    port: int | None = field(init=False)
    path: str | None = field(init=False)
    _db_params: RelayDbParams = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
        hash=False,  # type: ignore[assignment]  # mypy expects bool literal, field() accepts it at runtime
    )

    def __post_init__(self) -> None:
        """Validate that the URL is in canonical form and populate computed fields.

        Raises:
            TypeError: If field types are incorrect.
            ValueError: If the URL is not canonical, invalid, local, or contains null bytes.
        """
        validate_str_no_null(self.url, "url")
        validate_timestamp(self.discovered_at, "discovered_at")

        # Defence in depth: re-sanitize to guarantee canonical form even though
        # callers should pre-sanitize.  This duplicates the RFC 3986 parse in
        # _parse() below -- a deliberate "never trust input" trade-off.
        canonical = sanitize_relay_url(self.url)
        if canonical != self.url:
            raise ValueError(
                f"Relay URL is not in canonical form: {self.url!r} (expected {canonical!r})"
            )

        parsed = self._parse(self.url)

        object.__setattr__(self, "network", parsed["network"])
        object.__setattr__(self, "scheme", parsed["scheme"])
        object.__setattr__(self, "host", parsed["host"])
        object.__setattr__(self, "port", parsed["port"])
        object.__setattr__(self, "path", parsed["path"])

        object.__setattr__(self, "_db_params", self._compute_db_params())

    @staticmethod
    def _parse(url: str) -> dict[str, Any]:
        """Extract components from a canonical relay URL.

        The URL must already be validated and normalized by
        [sanitize_relay_url][bigbrotr.models.relay.sanitize_relay_url].
        Path normalization is intentionally not repeated here; it is
        performed once in ``sanitize_relay_url()`` and verified by the
        canonical form check in ``__post_init__``.

        Args:
            url: Canonical URL string.

        Returns:
            Dictionary containing ``scheme``, ``host``, ``port``, ``path``,
            and ``network``.
        """
        uri = uri_reference(url).normalize()

        port = int(uri.port) if uri.port else None
        host = uri.host.strip("[]") if uri.host else ""

        path = uri.path or None

        network = _detect_network(host)
        scheme = "wss" if network == NetworkType.CLEARNET else "ws"

        return {
            "scheme": scheme,
            "host": host,
            "port": port,
            "path": path,
            "network": network,
        }

    def _compute_db_params(self) -> RelayDbParams:
        """Compute positional parameters for the database insert procedure.

        Called once during ``__post_init__`` to populate the ``_db_params``
        cache. All subsequent access goes through
        [to_db_params()][bigbrotr.models.relay.Relay.to_db_params].

        Returns:
            [RelayDbParams][bigbrotr.models.relay.RelayDbParams] with the
            normalized URL, network name, and discovery timestamp.
        """
        return RelayDbParams(
            url=self.url,
            network=self.network,
            discovered_at=self.discovered_at,
        )

    def to_db_params(self) -> RelayDbParams:
        """Return cached positional parameters for the database insert procedure.

        The result is computed once during construction and cached for the
        lifetime of the (frozen) instance, avoiding repeated network name
        conversions.

        Returns:
            [RelayDbParams][bigbrotr.models.relay.RelayDbParams] with the
            normalized URL, network name, and discovery timestamp.
        """
        return self._db_params


def sanitize_relay_url(raw: str) -> str:
    """Normalize and clean a raw relay URL for untrusted input.

    Performs full canonicalization: RFC 3986 normalization, scheme enforcement
    (``wss://`` for clearnet, ``ws://`` for overlays), default port omission,
    query string and fragment stripping, and garbage path removal (control
    characters, whitespace, embedded URI schemes).

    The result is in canonical form and can be passed directly to
    :class:`Relay`.

    Args:
        raw: Raw URL string, potentially malformed.

    Returns:
        Canonical URL string with enforced scheme, host, optional port,
        and optional path.

    Raises:
        ValueError: If the URL is structurally unrecoverable (no scheme, no host,
            non-WebSocket scheme, local/private address, invalid hostname).
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

    host = uri.host.strip("[]") if uri.host else ""
    port = int(uri.port) if uri.port else None

    # Detect network and enforce the correct scheme
    network = _detect_network(host)
    if network == NetworkType.LOCAL:
        raise ValueError("Local addresses not allowed")
    if network == NetworkType.UNKNOWN:
        raise ValueError(f"Invalid host: '{host}'")

    scheme = "wss" if network == NetworkType.CLEARNET else "ws"

    # Sanitize the path: collapse slashes, strip trailing slash, then validate
    # each segment against RFC 3986 unreserved + ":" with alphanumeric boundaries.
    path = uri.path or ""
    while "//" in path:
        path = path.replace("//", "/")
    path = path.rstrip("/")

    if path:
        decoded = unquote(path)
        segments = [s for s in decoded.split("/") if s]
        if not all(
            set(s) <= _PATH_CHARS and s[0] in _PATH_BOUNDARY_CHARS and s[-1] in _PATH_BOUNDARY_CHARS
            for s in segments
        ):
            path = ""

    # Re-bracket IPv6 addresses for the final URL
    formatted_host = f"[{host}]" if ":" in host else host

    # Omit the port when it matches the default for the scheme
    default_port = _PORT_WSS if scheme == "wss" else _PORT_WS
    if port and port != default_port:
        url = f"{scheme}://{formatted_host}:{port}{path}"
    else:
        url = f"{scheme}://{formatted_host}{path}"

    if len(url) > _MAX_URL_LENGTH:
        raise ValueError(
            f"URL exceeds maximum length ({len(url)} > {_MAX_URL_LENGTH}): '{url[:80]}...'"
        )

    return url
