"""Kind 30166 tag building for NIP-66 relay discovery events.

Provides the [MonitorTagsMixin][bigbrotr.services.monitor_tags.MonitorTagsMixin]
class that is mixed into [Monitor][bigbrotr.services.monitor.Monitor] via
multiple inheritance. Converts
[CheckResult][bigbrotr.services.monitor.CheckResult] data into NIP-66
compliant tags for Kind 30166 events.

The following NIP-66 tag types are supported:

- **RTT tags**: ``rtt-open``, ``rtt-read``, ``rtt-write`` (milliseconds).
- **SSL tags**: ``ssl``, ``ssl-expires``, ``ssl-issuer``.
- **Net tags**: ``net-ip``, ``net-ipv6``, ``net-asn``, ``net-asn-org``.
- **Geo tags**: ``g`` (geohash), ``geo-country``, ``geo-city``,
  ``geo-lat``, ``geo-lon``, ``geo-tz``.
- **NIP-11 tags**: ``N`` (supported NIPs), ``t`` (topics), ``l``
  (ISO 639-1 languages), ``R`` (requirements), ``T`` (relay types).

Note:
    All tag values are formatted as strings per NIP-66. Numeric values
    (RTT, ASN, coordinates) are stringified. Boolean requirements use
    the ``!`` prefix for negation (e.g., ``!auth``, ``!payment``).

See Also:
    [Monitor][bigbrotr.services.monitor.Monitor]: The host class that
        composes this mixin.
    [MonitorPublisherMixin][bigbrotr.services.monitor_publisher.MonitorPublisherMixin]:
        Companion mixin that broadcasts the built events.
    [CheckResult][bigbrotr.services.monitor.CheckResult]: The data
        source for tag construction.
    [MetadataFlags][bigbrotr.services.monitor.MetadataFlags]: Controls
        which tag categories are included via ``discovery.include``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

from nostr_sdk import EventBuilder, Kind, Tag

from bigbrotr.models.constants import EventKind


if TYPE_CHECKING:
    from bigbrotr.models import Relay

    from .monitor import CheckResult, MetadataFlags


# =============================================================================
# Constants
# =============================================================================

# ISO 639-1 language code length
_ISO_639_1_LENGTH = 2

# NIP numbers for capability-based type tags
_NIP_CAP_SEARCH = 50
_NIP_CAP_COMMUNITY = 29
_NIP_CAP_BLOSSOM = 95


# =============================================================================
# Types
# =============================================================================


class _AccessFlags(NamedTuple):
    """Relay access restriction flags derived from NIP-11 and RTT probe results.

    Used internally by ``_add_requirement_and_type_tags`` to combine
    NIP-11 declared restrictions with actual RTT probe behavior.
    """

    payment: bool
    auth: bool
    writes: bool
    read_auth: bool


# =============================================================================
# Mixin
# =============================================================================


class MonitorTagsMixin:
    """Tag-building methods for Kind 30166 relay discovery events (NIP-66).

    Mixed into [Monitor][bigbrotr.services.monitor.Monitor] to provide
    tag construction without cluttering the main orchestration module.
    All methods assume that the host class provides ``self._config``
    ([MonitorConfig][bigbrotr.services.monitor.MonitorConfig]) with a
    ``discovery.include`` attribute of type
    [MetadataFlags][bigbrotr.services.monitor.MetadataFlags].

    Note:
        Tag formatting follows the NIP-66 specification strictly. All
        numeric values are converted to strings, geohash precision is
        configurable via ``processing.geohash_precision``, and language
        tags use ISO 639-1 two-letter codes.

    See Also:
        [MonitorPublisherMixin][bigbrotr.services.monitor_publisher.MonitorPublisherMixin]:
            Companion mixin that broadcasts the events built here.
        [CheckResult][bigbrotr.services.monitor.CheckResult]: The data
            source consumed by tag-building methods.
        [Monitor][bigbrotr.services.monitor.Monitor]: The host class
            that composes this mixin.
    """

    # -------------------------------------------------------------------------
    # Kind 30166 Tag Helpers
    # -------------------------------------------------------------------------

    def _add_rtt_tags(self, tags: list[Tag], result: CheckResult, include: MetadataFlags) -> None:
        """Add round-trip time tags: ``rtt-open``, ``rtt-read``, ``rtt-write``."""
        if not result.nip66_rtt or not include.nip66_rtt:
            return
        rtt_data = result.nip66_rtt.metadata.data.get("data", {})
        if rtt_data.get("rtt_open") is not None:
            tags.append(Tag.parse(["rtt-open", str(rtt_data["rtt_open"])]))
        if rtt_data.get("rtt_read") is not None:
            tags.append(Tag.parse(["rtt-read", str(rtt_data["rtt_read"])]))
        if rtt_data.get("rtt_write") is not None:
            tags.append(Tag.parse(["rtt-write", str(rtt_data["rtt_write"])]))

    def _add_ssl_tags(self, tags: list[Tag], result: CheckResult, include: MetadataFlags) -> None:
        """Add SSL certificate tags: ``ssl``, ``ssl-expires``, ``ssl-issuer``."""
        if not result.nip66_ssl or not include.nip66_ssl:
            return
        ssl_data = result.nip66_ssl.metadata.data.get("data", {})
        ssl_valid = ssl_data.get("ssl_valid")
        if ssl_valid is not None:
            tags.append(Tag.parse(["ssl", "valid" if ssl_valid else "!valid"]))
        ssl_expires = ssl_data.get("ssl_expires")
        if ssl_expires is not None:
            tags.append(Tag.parse(["ssl-expires", str(ssl_expires)]))
        ssl_issuer = ssl_data.get("ssl_issuer")
        if ssl_issuer:
            tags.append(Tag.parse(["ssl-issuer", ssl_issuer]))

    def _add_net_tags(self, tags: list[Tag], result: CheckResult, include: MetadataFlags) -> None:
        """Add network information tags: ``net-ip``, ``net-ipv6``, ``net-asn``, ``net-asn-org``."""
        if not result.nip66_net or not include.nip66_net:
            return
        net_data = result.nip66_net.metadata.data.get("data", {})
        net_ip = net_data.get("net_ip")
        if net_ip:
            tags.append(Tag.parse(["net-ip", net_ip]))
        net_ipv6 = net_data.get("net_ipv6")
        if net_ipv6:
            tags.append(Tag.parse(["net-ipv6", net_ipv6]))
        net_asn = net_data.get("net_asn")
        if net_asn is not None:
            tags.append(Tag.parse(["net-asn", str(net_asn)]))
        net_asn_org = net_data.get("net_asn_org")
        if net_asn_org:
            tags.append(Tag.parse(["net-asn-org", net_asn_org]))

    def _add_geo_tags(self, tags: list[Tag], result: CheckResult, include: MetadataFlags) -> None:
        """Add geolocation tags.

        Tags: ``g`` (geohash), ``geo-country``, ``geo-city``,
        ``geo-lat``, ``geo-lon``, ``geo-tz``.
        """
        if not result.nip66_geo or not include.nip66_geo:
            return
        geo_data = result.nip66_geo.metadata.data.get("data", {})
        geohash = geo_data.get("geo_hash")
        if geohash:
            tags.append(Tag.parse(["g", geohash]))
        geo_country = geo_data.get("geo_country")
        if geo_country:
            tags.append(Tag.parse(["geo-country", geo_country]))
        geo_city = geo_data.get("geo_city")
        if geo_city:
            tags.append(Tag.parse(["geo-city", geo_city]))
        geo_lat = geo_data.get("geo_lat")
        if geo_lat is not None:
            tags.append(Tag.parse(["geo-lat", str(geo_lat)]))
        geo_lon = geo_data.get("geo_lon")
        if geo_lon is not None:
            tags.append(Tag.parse(["geo-lon", str(geo_lon)]))
        geo_tz = geo_data.get("geo_tz")
        if geo_tz:
            tags.append(Tag.parse(["geo-tz", geo_tz]))

    def _add_nip11_tags(self, tags: list[Tag], result: CheckResult, include: MetadataFlags) -> None:
        """Add NIP-11-derived capability tags.

        Tags: ``N`` (NIPs), ``t`` (topics), ``l`` (languages),
        ``R`` (requirements), ``T`` (types).
        """
        if not result.nip11 or not include.nip11_info:
            return
        nip11_data = result.nip11.metadata.data.get("data", {})

        # N tags: supported NIPs
        supported_nips = nip11_data.get("supported_nips")
        if supported_nips:
            tags.extend(Tag.parse(["N", str(nip)]) for nip in supported_nips)

        # t tags: topic tags
        nip11_tags = nip11_data.get("tags")
        if nip11_tags:
            tags.extend(Tag.hashtag(topic) for topic in nip11_tags)

        # l tags: language tags (ISO-639-1)
        self._add_language_tags(tags, nip11_data)

        # R and T tags: requirements and types
        self._add_requirement_and_type_tags(tags, result, nip11_data, supported_nips)

    def _add_language_tags(self, tags: list[Tag], nip11_data: dict[str, Any]) -> None:
        """Add ISO 639-1 language tags derived from NIP-11 ``language_tags`` field.

        Note:
            Wildcard entries (``*``) cause all language tags to be
            skipped, as the relay accepts all languages. Primary subtags
            are extracted by splitting on ``-`` (e.g., ``en-US`` yields
            ``en``).
        """
        language_tags = nip11_data.get("language_tags")
        if not language_tags or "*" in language_tags:
            return
        seen_langs: set[str] = set()
        for lang in language_tags:
            primary = lang.split("-")[0].lower() if lang else ""
            if primary and len(primary) == _ISO_639_1_LENGTH and primary not in seen_langs:
                seen_langs.add(primary)
                tags.append(Tag.parse(["l", primary, "ISO-639-1"]))

    def _add_requirement_and_type_tags(
        self,
        tags: list[Tag],
        result: CheckResult,
        nip11_data: dict[str, Any],
        supported_nips: list[int] | None,
    ) -> None:
        """Add ``R`` and ``T`` tags from NIP-11 data and RTT probe logs.

        Note:
            Requirement determination uses a two-source strategy: NIP-11
            ``limitation`` fields declare what the relay claims, while
            RTT write probe logs reveal actual behavior. The final value
            is the union of both sources (either claiming a restriction
            is sufficient). Write restrictions are cleared if the probe
            actually succeeded.
        """
        limitation = nip11_data.get("limitation") or {}
        nip11_auth = limitation.get("auth_required", False)
        nip11_payment = limitation.get("payment_required", False)
        nip11_writes = limitation.get("restricted_writes", False)
        pow_diff = limitation.get("min_pow_difficulty", 0)

        # Get probe results from RTT logs for verification
        rtt_logs = result.nip66_rtt.metadata.data.get("logs", {}) if result.nip66_rtt else {}
        write_success = rtt_logs.get("write_success")
        write_reason = (rtt_logs.get("write_reason") or "").lower()
        read_success = rtt_logs.get("read_success")
        read_reason = (rtt_logs.get("read_reason") or "").lower()

        # Determine actual restrictions from RTT probe results
        if write_success is False and write_reason:
            rtt_auth = "auth" in write_reason
            rtt_payment = "pay" in write_reason or "paid" in write_reason
            rtt_writes = not rtt_auth and not rtt_payment
        else:
            rtt_auth = False
            rtt_payment = False
            rtt_writes = False

        # Final determination
        auth = bool(nip11_auth or rtt_auth)
        payment = bool(nip11_payment or rtt_payment)
        writes = False if write_success is True else bool(nip11_writes or rtt_writes)
        read_auth = read_success is False and "auth" in read_reason

        # R tags
        tags.append(Tag.parse(["R", "auth" if auth else "!auth"]))
        tags.append(Tag.parse(["R", "payment" if payment else "!payment"]))
        tags.append(Tag.parse(["R", "writes" if writes else "!writes"]))
        tags.append(Tag.parse(["R", "pow" if pow_diff and pow_diff > 0 else "!pow"]))

        # T tags: relay types
        access = _AccessFlags(payment=payment, auth=auth, writes=writes, read_auth=read_auth)
        self._add_type_tags(tags, supported_nips, access)

    def _add_type_tags(
        self,
        tags: list[Tag],
        supported_nips: list[int] | None,
        access: _AccessFlags,
    ) -> None:
        """Add ``T`` (type) tags classifying the relay based on NIPs and access restrictions.

        Note:
            Type classification follows NIP-66 conventions:

            - **Capability types** (``Search``, ``Community``, ``Blob``)
              are derived from supported NIP numbers (50, 29, 95).
            - **Access types** (``Paid``, ``PrivateStorage``,
              ``PrivateInbox``, ``PublicOutbox``, ``PublicInbox``) are
              derived from the combined NIP-11 + RTT access flags.
            - A relay can have multiple type tags.

        Args:
            tags: Mutable tag list to append to.
            supported_nips: NIP numbers advertised by the relay (from NIP-11).
            access: Relay access restriction flags derived from NIP-11
                and RTT probe results.
        """
        nips = set(supported_nips) if supported_nips else set()

        # Capability-based types (from supported_nips)
        if _NIP_CAP_SEARCH in nips:
            tags.append(Tag.parse(["T", "Search"]))
        if _NIP_CAP_COMMUNITY in nips:
            tags.append(Tag.parse(["T", "Community"]))
        if _NIP_CAP_BLOSSOM in nips:
            tags.append(Tag.parse(["T", "Blob"]))

        # Payment modifier
        if access.payment:
            tags.append(Tag.parse(["T", "Paid"]))

        # Determine primary access type based on read/write restrictions
        if access.read_auth:
            if access.auth:
                tags.append(Tag.parse(["T", "PrivateStorage"]))
            else:
                tags.append(Tag.parse(["T", "PrivateInbox"]))
        elif access.auth or access.writes or access.payment:
            tags.append(Tag.parse(["T", "PublicOutbox"]))
        else:
            tags.append(Tag.parse(["T", "PublicInbox"]))

    def _build_kind_30166(self, relay: Relay, result: CheckResult) -> EventBuilder:
        """Build a Kind 30166 relay discovery event per NIP-66.

        The event's ``d`` tag is the relay URL. The content field contains
        the stringified NIP-11 JSON document if available, per the NIP-66
        spec. Tags are added by the ``_add_*_tags`` helper methods based
        on the ``discovery.include``
        [MetadataFlags][bigbrotr.services.monitor.MetadataFlags].

        Note:
            Kind 30166 is a parameterized replaceable event (30000-39999
            range). The ``d`` tag (relay URL) acts as the replacement key,
            so each relay has at most one active discovery event per
            monitor identity.

        See Also:
            ``MonitorPublisherMixin._publish_relay_discoveries()``:
                Broadcasts the events built by this method.
        """
        include = self._config.discovery.include  # type: ignore[attr-defined]
        content = result.nip11.metadata.canonical_json if result.nip11 else ""
        tags: list[Tag] = [
            Tag.identifier(relay.url),
            Tag.parse(["n", relay.network.value]),
        ]

        # Add NIP-66 metadata tags
        self._add_rtt_tags(tags, result, include)
        self._add_ssl_tags(tags, result, include)
        self._add_net_tags(tags, result, include)
        self._add_geo_tags(tags, result, include)

        # Add NIP-11 capability tags
        self._add_nip11_tags(tags, result, include)

        return EventBuilder(Kind(EventKind.RELAY_DISCOVERY), content).tags(tags)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "MonitorTagsMixin",
]
