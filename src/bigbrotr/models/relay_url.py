"""Relay URL normalization and network classification helpers."""

from __future__ import annotations

from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network
from typing import NamedTuple
from urllib.parse import unquote

from rfc3986 import uri_reference
from rfc3986.exceptions import UnpermittedComponentError, ValidationError
from rfc3986.validators import Validator

from .constants import NetworkType


class RelayUrlParts(NamedTuple):
    """Canonical relay URL components used to populate a Relay."""

    scheme: str
    host: str
    port: int | None
    path: str | None
    network: NetworkType


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


def detect_relay_network(host: str) -> NetworkType:
    """Classify a hostname or IP address into a relay network type."""
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


def parse_canonical_relay_url(url: str) -> RelayUrlParts:
    """Parse an already canonical relay URL into typed components."""
    uri = uri_reference(url).normalize()

    port = int(uri.port) if uri.port else None
    host = uri.host.strip("[]") if uri.host else ""
    path = uri.path or None

    return RelayUrlParts(
        scheme=uri.scheme.lower(),
        host=host,
        port=port,
        path=path,
        network=detect_relay_network(host),
    )


def normalize_relay_url(raw: str, *, allow_local: bool = False) -> str:
    """Normalize and canonicalize a raw relay URL from untrusted input."""
    uri = uri_reference(_preprocess_idn(raw.strip())).normalize()

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

    host = unquote(uri.host.strip("[]")) if uri.host else ""
    host = host.rstrip(".")
    if host != host.strip() or any(c in host for c in " \t\n\r\x00\\"):
        raise ValueError(f"Invalid host: '{host[:50]}'")

    network = detect_relay_network(host)
    if network == NetworkType.LOCAL and not allow_local:
        raise ValueError("Local addresses not allowed")
    if network == NetworkType.UNKNOWN:
        raise ValueError(f"Invalid host: '{host}'")

    host = _normalize_ip(host)
    if network == NetworkType.CLEARNET:
        scheme = "wss"
    elif network == NetworkType.LOCAL:
        scheme = uri.scheme.lower()
    else:
        scheme = "ws"

    port = int(uri.port) if uri.port else None
    if port is not None and not _PORT_MIN <= port <= _PORT_MAX:
        raise ValueError(f"Port out of range: {port}")

    path = _sanitize_path(uri.path)

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


def _is_valid_hostname(host: str) -> bool:
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

    return False  # pragma: no cover


def _preprocess_idn(raw: str) -> str:
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
    try:
        return str(ip_address(host))
    except ValueError:
        return host


def _sanitize_path(raw_path: str) -> str:
    path = raw_path or ""
    while "//" in path:
        path = path.replace("//", "/")
    path = path.rstrip("/")

    if not path:
        return ""

    decoded = unquote(path)
    segments = [s for s in decoded.split("/") if s]
    if not all(
        set(s) <= _PATH_CHARS and s[0] in _PATH_BOUNDARY_CHARS and s[-1] in _PATH_BOUNDARY_CHARS
        for s in segments
    ):
        return ""

    return path


__all__ = [
    "RelayUrlParts",
    "detect_relay_network",
    "normalize_relay_url",
    "parse_canonical_relay_url",
]
