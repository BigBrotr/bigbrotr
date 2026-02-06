"""
NIP-66 monitoring data models.

Defines the typed Pydantic models for each NIP-66 monitoring test result:
RTT (round-trip time), SSL certificate, geolocation, network/ASN,
DNS resolution, and HTTP server headers.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import StrictBool, StrictFloat, StrictInt

from models.nips.base import BaseData
from models.nips.parsing import FieldSpec


class Nip66RttData(BaseData):
    """Round-trip time measurements in milliseconds.

    Captures connection open, event read, and event write latencies.
    """

    rtt_open: StrictInt | None = None
    rtt_read: StrictInt | None = None
    rtt_write: StrictInt | None = None

    _FIELD_SPEC: ClassVar[FieldSpec] = FieldSpec(
        int_fields=frozenset({"rtt_open", "rtt_read", "rtt_write"}),
    )


class Nip66SslData(BaseData):
    """SSL/TLS certificate details extracted from a relay connection.

    Includes certificate identity, validity dates, Subject Alternative Names,
    fingerprint, and negotiated cipher information.
    """

    ssl_valid: StrictBool | None = None
    ssl_subject_cn: str | None = None
    ssl_issuer: str | None = None
    ssl_issuer_cn: str | None = None
    ssl_expires: StrictInt | None = None
    ssl_not_before: StrictInt | None = None
    ssl_san: list[str] | None = None
    ssl_serial: str | None = None
    ssl_version: StrictInt | None = None
    ssl_fingerprint: str | None = None
    ssl_protocol: str | None = None
    ssl_cipher: str | None = None
    ssl_cipher_bits: StrictInt | None = None

    _FIELD_SPEC: ClassVar[FieldSpec] = FieldSpec(
        bool_fields=frozenset({"ssl_valid"}),
        int_fields=frozenset(
            {
                "ssl_expires",
                "ssl_not_before",
                "ssl_version",
                "ssl_cipher_bits",
            }
        ),
        str_fields=frozenset(
            {
                "ssl_subject_cn",
                "ssl_issuer",
                "ssl_issuer_cn",
                "ssl_serial",
                "ssl_fingerprint",
                "ssl_protocol",
                "ssl_cipher",
            }
        ),
        str_list_fields=frozenset({"ssl_san"}),
    )


class Nip66GeoData(BaseData):
    """Geolocation data derived from GeoIP database lookups.

    Includes country, continent, city, coordinates, timezone, and a
    geohash computed from latitude/longitude.
    """

    geo_country: str | None = None
    geo_country_name: str | None = None
    geo_continent: str | None = None
    geo_continent_name: str | None = None
    geo_is_eu: StrictBool | None = None
    geo_region: str | None = None
    geo_city: str | None = None
    geo_postal: str | None = None
    geo_lat: StrictFloat | None = None
    geo_lon: StrictFloat | None = None
    geo_accuracy: StrictInt | None = None
    geo_tz: str | None = None
    geohash: str | None = None
    geo_geoname_id: StrictInt | None = None

    _FIELD_SPEC: ClassVar[FieldSpec] = FieldSpec(
        bool_fields=frozenset({"geo_is_eu"}),
        int_fields=frozenset({"geo_accuracy", "geo_geoname_id"}),
        float_fields=frozenset({"geo_lat", "geo_lon"}),
        str_fields=frozenset(
            {
                "geo_country",
                "geo_country_name",
                "geo_continent",
                "geo_continent_name",
                "geo_region",
                "geo_city",
                "geo_postal",
                "geo_tz",
                "geohash",
            }
        ),
    )


class Nip66NetData(BaseData):
    """Network and ASN information from GeoIP ASN database lookups.

    Includes resolved IP addresses, autonomous system number and
    organization, and CIDR network ranges.
    """

    net_ip: str | None = None
    net_ipv6: str | None = None
    net_asn: StrictInt | None = None
    net_asn_org: str | None = None
    net_network: str | None = None
    net_network_v6: str | None = None

    _FIELD_SPEC: ClassVar[FieldSpec] = FieldSpec(
        int_fields=frozenset({"net_asn"}),
        str_fields=frozenset(
            {
                "net_ip",
                "net_ipv6",
                "net_asn_org",
                "net_network",
                "net_network_v6",
            }
        ),
    )


class Nip66DnsData(BaseData):
    """DNS resolution results for a relay hostname.

    Includes A/AAAA records, CNAME, reverse DNS (PTR), nameservers,
    and record TTL.
    """

    dns_ips: list[str] | None = None
    dns_ips_v6: list[str] | None = None
    dns_cname: str | None = None
    dns_reverse: str | None = None
    dns_ns: list[str] | None = None
    dns_ttl: StrictInt | None = None

    _FIELD_SPEC: ClassVar[FieldSpec] = FieldSpec(
        int_fields=frozenset({"dns_ttl"}),
        str_fields=frozenset({"dns_cname", "dns_reverse"}),
        str_list_fields=frozenset({"dns_ips", "dns_ips_v6", "dns_ns"}),
    )


class Nip66HttpData(BaseData):
    """HTTP server headers captured during WebSocket handshake.

    Records the ``Server`` and ``X-Powered-By`` response headers.
    """

    http_server: str | None = None
    http_powered_by: str | None = None

    _FIELD_SPEC: ClassVar[FieldSpec] = FieldSpec(
        str_fields=frozenset({"http_server", "http_powered_by"}),
    )
