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


# Hostname labels: RFC 952 allows [a-z0-9-] but RFC 2181 §11 imposes no charset
# restriction on DNS labels, and underscores are widespread in practice (SRV records,
# Coracle rooms, Nostr relay subdomains). We accept [a-z0-9-_].
_HOSTNAME_LABEL_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-_")
_HOSTNAME_MAX_LABEL_LENGTH = 63
_HOSTNAME_MAX_LENGTH = 253

# Overlay network hostname validation.
# Base32 alphabet used by Tor v3, I2P b32, and Lokinet.
_BASE32_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz234567")
_ONION_V3_LENGTH = 56
_ONION_V2_LENGTH = 16
_I2P_B32_LENGTH = 52
_LOKI_LENGTH = 52

# RFC 3986 unreserved characters plus ":" (allowed in pchar).
_PATH_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~:")

# Characters that may appear at the start or end of a path segment.
# Non-alphanumeric unreserved chars (-, ., _, ~) and ":" are only valid mid-segment.
_PATH_BOUNDARY_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")

_PORT_WS = 80
_PORT_WSS = 443
_PORT_MIN = 1
_PORT_MAX = 65535
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
    IANA special-purpose registries, and finally validates the hostname
    against RFC 952/1123 (label charset, length, no numeric-only TLD).

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
            name = host_bare[: -len(tld)]
            if not _is_valid_overlay_hostname(name, network):
                return NetworkType.UNKNOWN
            return network

    if host_bare in ("localhost", "localhost.localdomain"):
        return NetworkType.LOCAL

    try:
        ip = ip_address(host_bare)
        is_local = any(ip in net for net in _LOCAL_NETWORKS)
        return NetworkType.LOCAL if is_local else NetworkType.CLEARNET
    except ValueError:
        pass

    return NetworkType.CLEARNET if _is_valid_hostname(host_bare) else NetworkType.UNKNOWN


def _is_valid_hostname(host: str) -> bool:
    """Check whether a hostname conforms to RFC 952/1123.

    Rules:
        - At least one dot (no single-label hostnames).
        - Total length <= 253 characters.
        - Each label: 1-63 characters, ``[a-z0-9-]`` only, no leading/trailing ``-``.
        - TLD must contain at least one letter (no numeric-only TLDs).
    """
    if "." not in host or len(host) > _HOSTNAME_MAX_LENGTH:
        return False

    labels = host.split(".")
    if not all(
        label
        and len(label) <= _HOSTNAME_MAX_LABEL_LENGTH
        and not label.startswith("-")
        and not label.endswith("-")
        and set(label) <= _HOSTNAME_LABEL_CHARS
        for label in labels
    ):
        return False

    return not labels[-1].isdigit()


def _is_valid_overlay_hostname(name: str, network: NetworkType) -> bool:
    """Validate the hostname portion (without TLD) of an overlay address.

    Rules per network:
        - **Tor** (``.onion``): rightmost label must be a 56-char base32 v3
          hash (or 16-char v2). Optional subdomain labels to the left are
          validated as standard hostname labels (RFC 7686 §2).
        - **I2P** (``.i2p``): 52-char base32 hash (``*.b32.i2p``) or
          human-readable hostname (standard labels).
        - **Loki** (``.loki``): 52-char base32.
    """
    if not name:
        return False

    if network == NetworkType.TOR:
        parts = name.rsplit(".", 1)
        onion_hash = parts[-1]
        valid_hash = (
            len(onion_hash) in (_ONION_V3_LENGTH, _ONION_V2_LENGTH)
            and set(onion_hash) <= _BASE32_CHARS
        )
        return valid_hash and (len(parts) == 1 or _is_valid_hostname(parts[0] + ".onion"))

    if network == NetworkType.LOKI:
        return len(name) == _LOKI_LENGTH and set(name) <= _BASE32_CHARS

    if network == NetworkType.I2P:
        if name.endswith(".b32"):
            b32_part = name[:-4]
            return len(b32_part) == _I2P_B32_LENGTH and set(b32_part) <= _BASE32_CHARS
        return _is_valid_hostname(name + ".i2p")

    return False


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


def _encode_idn_host(raw: str) -> str:
    """Convert internationalized domain labels to ASCII punycode in-place.

    Locates the host portion of a raw URL and converts non-ASCII labels
    through the stdlib ``encodings.idna`` codec (IDNA 2003) so that
    downstream RFC 3986 parsing receives a pure-ASCII URL.  ASCII labels
    (which may contain underscores) are left untouched.

    Must run *before* ``uri_reference()`` because RFC 3986 is ASCII-only.
    """
    if raw.isascii():
        return raw
    scheme_end = raw.find("://")
    if scheme_end == -1:
        return raw
    prefix = raw[: scheme_end + 3]
    after = raw[scheme_end + 3 :]
    host_end = len(after)
    for ch in "/:?#":
        pos = after.find(ch)
        if pos != -1 and pos < host_end:
            host_end = pos
    host = after[:host_end]
    rest = after[host_end:]
    if host.isascii():
        return raw
    labels = host.split(".")
    converted: list[str] = []
    for label in labels:
        if label.isascii():
            converted.append(label)
            continue
        try:
            converted.append(label.encode("idna").decode("ascii"))
        except (UnicodeError, UnicodeDecodeError):
            raise ValueError(f"Invalid internationalized hostname: '{host[:50]}'") from None
    return prefix + ".".join(converted) + rest


def _normalize_ip(host: str) -> str:
    """Normalize IP address representation.

    IPv6 addresses are compressed to canonical form (RFC 5952):
    ``2001:0db8::0001`` → ``2001:db8::1``.  IPv4 addresses with
    leading zeros are rejected by Python's ``ipaddress`` module
    (ambiguous octal/decimal), which is the desired behavior.
    Non-IP hostnames pass through unchanged.
    """
    try:
        return str(ip_address(host))
    except ValueError:
        return host


def _resolve_dot_segments(path: str) -> str:
    """Resolve ``.`` and ``..`` segments in a URL path per RFC 3986 §5.2.4.

    Traversal above the root is silently clamped (``/../a`` → ``/a``).
    """
    if "/." not in path:
        return path
    segments = path.split("/")
    output: list[str] = []
    for s in segments:
        if s == ".":
            continue
        if s == "..":
            if len(output) > 1:
                output.pop()
            continue
        output.append(s)
    return "/".join(output)


def _sanitize_path(raw_path: str) -> str:
    """Normalize and validate a URL path component.

    Collapses double slashes, strips trailing slashes, resolves dot
    segments (RFC 3986 §5.2.4), then validates each segment against
    the allowed character set.  Returns empty string if the path
    contains invalid segments.
    """
    path = raw_path or ""
    while "//" in path:
        path = path.replace("//", "/")
    path = path.rstrip("/")

    if not path:
        return ""

    path = _resolve_dot_segments(path)
    decoded = unquote(path)
    segments = [s for s in decoded.split("/") if s]
    if not all(
        set(s) <= _PATH_CHARS and s[0] in _PATH_BOUNDARY_CHARS and s[-1] in _PATH_BOUNDARY_CHARS
        for s in segments
    ):
        return ""

    return path


def sanitize_relay_url(raw: str) -> str:
    """Normalize and canonicalize a raw relay URL from untrusted input.

    Applies the full normalization pipeline:

    1. **RFC 3986 parsing** — scheme, host, port, path decomposition.
    2. **Host normalization** — percent-decoding, trailing-dot removal,
       IDN-to-punycode conversion, whitespace/control-char rejection,
       IP address canonicalization (IPv6 compression, IPv4 validation).
    3. **Network detection** — overlay TLD matching (``.onion``, ``.i2p``,
       ``.loki``), private/reserved IP rejection, hostname validation.
    4. **Scheme enforcement** — ``wss://`` for clearnet, ``ws://`` for overlays.
    5. **Port normalization** — range validation (1-65535), default port
       omission (443 for ``wss``, 80 for ``ws``).
    6. **Path normalization** — slash collapsing, dot-segment resolution
       (RFC 3986 §5.2.4), trailing-slash removal, segment validation.
    7. **Query/fragment stripping** — irrelevant for WebSocket relay identity.

    Args:
        raw: Raw URL string, potentially malformed.

    Returns:
        Canonical URL string suitable for :class:`Relay` construction.

    Raises:
        ValueError: If the URL is structurally unrecoverable.
    """
    uri = uri_reference(_encode_idn_host(raw.strip())).normalize()

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

    # --- Host normalization ---
    host = unquote(uri.host.strip("[]")) if uri.host else ""
    host = host.rstrip(".")
    if host != host.strip() or any(c in host for c in " \t\n\r\x00\\"):
        raise ValueError(f"Invalid host: '{host[:50]}'")

    # --- Network classification and rejection ---
    network = _detect_network(host)
    if network == NetworkType.LOCAL:
        raise ValueError("Local addresses not allowed")
    if network == NetworkType.UNKNOWN:
        raise ValueError(f"Invalid host: '{host}'")

    host = _normalize_ip(host)
    scheme = "wss" if network == NetworkType.CLEARNET else "ws"

    # --- Port validation ---
    port = int(uri.port) if uri.port else None
    if port is not None and not _PORT_MIN <= port <= _PORT_MAX:
        raise ValueError(f"Port out of range: {port}")

    # --- Path normalization ---
    path = _sanitize_path(uri.path)

    # --- URL reconstruction ---
    formatted_host = f"[{host}]" if ":" in host else host
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
