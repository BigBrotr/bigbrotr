"""Nostr event builders for all NIP-compliant event kinds.

Standalone functions for constructing Nostr events from typed NIP data
models. Used by the Monitor service for publishing profile (Kind 0),
monitor announcement (Kind 10166), and relay discovery (Kind 30166) events.

See Also:
    [bigbrotr.nips.nip66.data][bigbrotr.nips.nip66.data]: Typed data models
        consumed by the Kind 30166 tag builder functions.
    [bigbrotr.nips.nip11.data.Nip11InfoData][bigbrotr.nips.nip11.data.Nip11InfoData]:
        NIP-11 data model used for language, requirement, and type tags.
    [bigbrotr.nips.nip66.logs.Nip66RttMultiPhaseLogs][bigbrotr.nips.nip66.logs.Nip66RttMultiPhaseLogs]:
        RTT probe logs used for requirement tag derivation.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, NamedTuple

from nostr_sdk import EventBuilder, Kind, Tag
from nostr_sdk import Metadata as NostrMetadata

from bigbrotr.models.constants import EventKind, NetworkType


if TYPE_CHECKING:
    from bigbrotr.nips.nip11.data import Nip11InfoData
    from bigbrotr.nips.nip11.nip11 import Nip11Selection
    from bigbrotr.nips.nip66.data import Nip66GeoData, Nip66NetData, Nip66RttData, Nip66SslData
    from bigbrotr.nips.nip66.logs import Nip66RttMultiPhaseLogs
    from bigbrotr.nips.nip66.nip66 import Nip66Selection


# =============================================================================
# Constants
# =============================================================================

_ISO_639_1_LENGTH = 2

_NIP_CAP_SEARCH = 50
_NIP_CAP_COMMUNITY = 29
_NIP_CAP_BLOSSOM = 95


# =============================================================================
# Types
# =============================================================================


class AccessFlags(NamedTuple):
    """Relay access restriction flags derived from NIP-11 and RTT probe results."""

    payment: bool
    auth: bool
    writes: bool
    read_auth: bool


# =============================================================================
# Kind 0 (NIP-01)
# =============================================================================


def build_profile_event(  # noqa: PLR0913
    *,
    name: str | None = None,
    about: str | None = None,
    picture: str | None = None,
    nip05: str | None = None,
    website: str | None = None,
    banner: str | None = None,
    lud16: str | None = None,
) -> EventBuilder:
    """Build a Kind 0 profile metadata event per NIP-01."""
    profile_data: dict[str, str] = {}
    if name:
        profile_data["name"] = name
    if about:
        profile_data["about"] = about
    if picture:
        profile_data["picture"] = picture
    if nip05:
        profile_data["nip05"] = nip05
    if website:
        profile_data["website"] = website
    if banner:
        profile_data["banner"] = banner
    if lud16:
        profile_data["lud16"] = lud16
    return EventBuilder.metadata(NostrMetadata.from_json(json.dumps(profile_data)))


# =============================================================================
# Kind 10166 (NIP-66)
# =============================================================================


def build_monitor_announcement(
    *,
    interval: int,
    timeout_ms: int,
    enabled_networks: list[NetworkType],
    nip11_selection: Nip11Selection,
    nip66_selection: Nip66Selection,
) -> EventBuilder:
    """Build a Kind 10166 monitor announcement event per NIP-66."""
    tags = [Tag.parse(["frequency", str(interval)])]
    tags.extend(Tag.parse(["n", network.value]) for network in enabled_networks)

    ms = str(timeout_ms)

    # Timeout tags — only NIP-66 check types that have timeouts
    if nip66_selection.rtt:
        tags.extend(Tag.parse(["timeout", name, ms]) for name in ("open", "read", "write"))
    if nip11_selection.info:
        tags.append(Tag.parse(["timeout", "nip11", ms]))
    if nip66_selection.ssl:
        tags.append(Tag.parse(["timeout", "ssl", ms]))

    # Capability tags — all NIP-66 check types (includes geo/net which have no timeout)
    if nip66_selection.rtt:
        tags.extend(Tag.parse(["c", name]) for name in ("open", "read", "write"))
    if nip11_selection.info:
        tags.append(Tag.parse(["c", "nip11"]))
    if nip66_selection.ssl:
        tags.append(Tag.parse(["c", "ssl"]))
    if nip66_selection.geo:
        tags.append(Tag.parse(["c", "geo"]))
    if nip66_selection.net:
        tags.append(Tag.parse(["c", "net"]))

    return EventBuilder(Kind(EventKind.MONITOR_ANNOUNCEMENT), "").tags(tags)


# =============================================================================
# Kind 30166 Tags (NIP-66)
# =============================================================================


def add_rtt_tags(tags: list[Tag], rtt_data: Nip66RttData | None) -> None:
    """Add round-trip time tags: ``rtt-open``, ``rtt-read``, ``rtt-write``."""
    if rtt_data is None:
        return
    if rtt_data.rtt_open is not None:
        tags.append(Tag.parse(["rtt-open", str(rtt_data.rtt_open)]))
    if rtt_data.rtt_read is not None:
        tags.append(Tag.parse(["rtt-read", str(rtt_data.rtt_read)]))
    if rtt_data.rtt_write is not None:
        tags.append(Tag.parse(["rtt-write", str(rtt_data.rtt_write)]))


def add_ssl_tags(tags: list[Tag], ssl_data: Nip66SslData | None) -> None:
    """Add SSL certificate tags: ``ssl``, ``ssl-expires``, ``ssl-issuer``."""
    if ssl_data is None:
        return
    if ssl_data.ssl_valid is not None:
        tags.append(Tag.parse(["ssl", "valid" if ssl_data.ssl_valid else "!valid"]))
    if ssl_data.ssl_expires is not None:
        tags.append(Tag.parse(["ssl-expires", str(ssl_data.ssl_expires)]))
    if ssl_data.ssl_issuer:
        tags.append(Tag.parse(["ssl-issuer", ssl_data.ssl_issuer]))


def add_net_tags(tags: list[Tag], net_data: Nip66NetData | None) -> None:
    """Add network tags: ``net-ip``, ``net-ipv6``, ``net-asn``, ``net-asn-org``."""
    if net_data is None:
        return
    if net_data.net_ip:
        tags.append(Tag.parse(["net-ip", net_data.net_ip]))
    if net_data.net_ipv6:
        tags.append(Tag.parse(["net-ipv6", net_data.net_ipv6]))
    if net_data.net_asn is not None:
        tags.append(Tag.parse(["net-asn", str(net_data.net_asn)]))
    if net_data.net_asn_org:
        tags.append(Tag.parse(["net-asn-org", net_data.net_asn_org]))


def add_geo_tags(tags: list[Tag], geo_data: Nip66GeoData | None) -> None:
    """Add geolocation tags (``g``, ``geo-country``, ``geo-city``, etc.)."""
    if geo_data is None:
        return
    if geo_data.geo_hash:
        tags.append(Tag.parse(["g", geo_data.geo_hash]))
    if geo_data.geo_country:
        tags.append(Tag.parse(["geo-country", geo_data.geo_country]))
    if geo_data.geo_city:
        tags.append(Tag.parse(["geo-city", geo_data.geo_city]))
    if geo_data.geo_lat is not None:
        tags.append(Tag.parse(["geo-lat", str(geo_data.geo_lat)]))
    if geo_data.geo_lon is not None:
        tags.append(Tag.parse(["geo-lon", str(geo_data.geo_lon)]))
    if geo_data.geo_tz:
        tags.append(Tag.parse(["geo-tz", geo_data.geo_tz]))


def add_language_tags(tags: list[Tag], nip11_data: Nip11InfoData) -> None:
    """Add ISO 639-1 language tags derived from NIP-11 ``language_tags`` field."""
    language_tags = nip11_data.language_tags
    if not language_tags or "*" in language_tags:
        return
    seen_langs: set[str] = set()
    for lang in language_tags:
        primary = lang.split("-")[0].lower() if lang else ""
        if primary and len(primary) == _ISO_639_1_LENGTH and primary not in seen_langs:
            seen_langs.add(primary)
            tags.append(Tag.parse(["l", primary, "ISO-639-1"]))


def add_requirement_and_type_tags(
    tags: list[Tag],
    nip11_data: Nip11InfoData,
    rtt_logs: Nip66RttMultiPhaseLogs | None,
) -> None:
    """Add ``R`` (requirement) and ``T`` (type) tags from NIP-11 data and RTT probe logs."""
    limitation = nip11_data.limitation
    nip11_auth = limitation.auth_required or False
    nip11_payment = limitation.payment_required or False
    nip11_writes = limitation.restricted_writes or False
    pow_diff = limitation.min_pow_difficulty or 0

    write_success: bool | None = None
    write_reason = ""
    read_success: bool | None = None
    read_reason = ""
    if rtt_logs is not None:
        write_success = rtt_logs.write_success
        write_reason = (rtt_logs.write_reason or "").lower()
        read_success = rtt_logs.read_success
        read_reason = (rtt_logs.read_reason or "").lower()

    # NIP-66 probes are ground truth; NIP-11 is relay self-report (fallback only)
    if write_success is True:
        # Probe wrote successfully without auth or payment — relay is open
        auth = False
        payment = False
        writes = False
    elif write_success is False and write_reason:
        # Probe failed — trust failure reason, augment with NIP-11 where probe is ambiguous
        rtt_auth = "auth" in write_reason
        rtt_payment = "pay" in write_reason or "paid" in write_reason
        auth = bool(rtt_auth or nip11_auth)
        payment = bool(rtt_payment or nip11_payment)
        writes = bool(not rtt_auth and not rtt_payment)
    else:
        # No probe results — NIP-11 is all we have
        auth = bool(nip11_auth)
        payment = bool(nip11_payment)
        writes = bool(nip11_writes)

    read_auth = read_success is False and "auth" in read_reason

    # R tags
    tags.append(Tag.parse(["R", "auth" if auth else "!auth"]))
    tags.append(Tag.parse(["R", "payment" if payment else "!payment"]))
    tags.append(Tag.parse(["R", "writes" if writes else "!writes"]))
    tags.append(Tag.parse(["R", "pow" if pow_diff and pow_diff > 0 else "!pow"]))

    # T tags
    access = AccessFlags(payment=payment, auth=auth, writes=writes, read_auth=read_auth)
    add_type_tags(tags, nip11_data.supported_nips, access)


def add_type_tags(
    tags: list[Tag],
    supported_nips: list[int] | None,
    access: AccessFlags,
) -> None:
    """Add ``T`` (type) tags classifying the relay based on NIPs and access restrictions."""
    nips = set(supported_nips) if supported_nips else set()

    if _NIP_CAP_SEARCH in nips:
        tags.append(Tag.parse(["T", "Search"]))
    if _NIP_CAP_COMMUNITY in nips:
        tags.append(Tag.parse(["T", "Community"]))
    if _NIP_CAP_BLOSSOM in nips:
        tags.append(Tag.parse(["T", "Blob"]))

    if access.payment:
        tags.append(Tag.parse(["T", "Paid"]))

    if access.read_auth:
        if access.auth:
            tags.append(Tag.parse(["T", "PrivateStorage"]))
        else:
            tags.append(Tag.parse(["T", "PrivateInbox"]))
    elif access.auth or access.writes or access.payment:
        tags.append(Tag.parse(["T", "PublicOutbox"]))
    else:
        tags.append(Tag.parse(["T", "PublicInbox"]))


def add_nip11_tags(
    tags: list[Tag],
    nip11_data: Nip11InfoData | None,
    rtt_logs: Nip66RttMultiPhaseLogs | None = None,
) -> None:
    """Add NIP-11-derived tags: ``N``, ``t``, ``l``, ``R``, ``T``."""
    if nip11_data is None:
        return

    if nip11_data.supported_nips:
        tags.extend(Tag.parse(["N", str(nip)]) for nip in nip11_data.supported_nips)

    if nip11_data.tags:
        tags.extend(Tag.hashtag(topic) for topic in nip11_data.tags)

    add_language_tags(tags, nip11_data)
    add_requirement_and_type_tags(tags, nip11_data, rtt_logs)


# =============================================================================
# Kind 30166 Builder (NIP-66)
# =============================================================================


def build_relay_discovery(  # noqa: PLR0913
    relay_url: str,
    network_value: str,
    nip11_canonical_json: str = "",
    *,
    rtt_data: Nip66RttData | None = None,
    ssl_data: Nip66SslData | None = None,
    net_data: Nip66NetData | None = None,
    geo_data: Nip66GeoData | None = None,
    nip11_data: Nip11InfoData | None = None,
    rtt_logs: Nip66RttMultiPhaseLogs | None = None,
) -> EventBuilder:
    """Build a Kind 30166 relay discovery event per NIP-66."""
    tags: list[Tag] = [
        Tag.identifier(relay_url),
        Tag.parse(["n", network_value]),
    ]

    add_rtt_tags(tags, rtt_data)
    add_ssl_tags(tags, ssl_data)
    add_net_tags(tags, net_data)
    add_geo_tags(tags, geo_data)
    add_nip11_tags(tags, nip11_data, rtt_logs)

    return EventBuilder(Kind(EventKind.RELAY_DISCOVERY), nip11_canonical_json).tags(tags)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "AccessFlags",
    "add_geo_tags",
    "add_language_tags",
    "add_net_tags",
    "add_nip11_tags",
    "add_requirement_and_type_tags",
    "add_rtt_tags",
    "add_ssl_tags",
    "add_type_tags",
    "build_monitor_announcement",
    "build_profile_event",
    "build_relay_discovery",
]
