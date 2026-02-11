"""
NIP-66 monitoring data models.

Defines the typed Pydantic models for each
[NIP-66](https://github.com/nostr-protocol/nips/blob/master/66.md) monitoring
test result: RTT (round-trip time), SSL certificate, geolocation,
network/ASN, DNS resolution, and HTTP server headers.

Note:
    All data classes extend [BaseData][bigbrotr.nips.base.BaseData] and use
    declarative [FieldSpec][bigbrotr.nips.parsing.FieldSpec] parsing.
    Field names are prefixed with their test type (e.g., ``rtt_``, ``ssl_``,
    ``geo_``, ``net_``, ``dns_``, ``http_``) to avoid collisions when
    multiple test results are serialized alongside each other.

See Also:
    [bigbrotr.nips.nip66.logs][bigbrotr.nips.nip66.logs]: Corresponding log
        models for each test type.
    [bigbrotr.nips.nip66.nip66.Nip66][bigbrotr.nips.nip66.nip66.Nip66]:
        Top-level model that aggregates all test results.
    [bigbrotr.nips.base.BaseData][bigbrotr.nips.base.BaseData]: Base class
        providing the ``parse()`` / ``from_dict()`` / ``to_dict()`` interface.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import StrictBool, StrictFloat, StrictInt  # noqa: TC002

from bigbrotr.nips.base import BaseData
from bigbrotr.nips.parsing import FieldSpec


class Nip66RttData(BaseData):
    """Round-trip time measurements in milliseconds.

    Captures connection open, event read, and event write latencies.

    Note:
        RTT values are measured using ``time.perf_counter()`` and converted
        to integer milliseconds. A ``None`` value indicates the corresponding
        phase was not reached (e.g., read/write are ``None`` if open failed).

    See Also:
        [bigbrotr.nips.nip66.rtt.Nip66RttMetadata][bigbrotr.nips.nip66.rtt.Nip66RttMetadata]:
            Container that pairs this data with multi-phase logs.
        [bigbrotr.nips.nip66.logs.Nip66RttMultiPhaseLogs][bigbrotr.nips.nip66.logs.Nip66RttMultiPhaseLogs]:
            Corresponding log model with per-phase success/reason.
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

    Note:
        Certificate extraction uses a non-validating SSL context
        (``CERT_NONE``) to read the certificate regardless of chain validity.
        Chain validation is performed separately and recorded in ``ssl_valid``.
        The fingerprint is a SHA-256 hash of the DER-encoded certificate.

    See Also:
        [bigbrotr.nips.nip66.ssl.Nip66SslMetadata][bigbrotr.nips.nip66.ssl.Nip66SslMetadata]:
            Container that pairs this data with SSL inspection logs.
        [bigbrotr.nips.nip66.ssl.CertificateExtractor][bigbrotr.nips.nip66.ssl.CertificateExtractor]:
            Utility class that extracts fields from Python SSL cert dicts.
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

    Note:
        The geohash is computed at precision 9 by default (approximately
        5 meters), using the ``geohash2`` library. Country data prefers the
        physical country over the registered country when available.

    See Also:
        [bigbrotr.nips.nip66.geo.Nip66GeoMetadata][bigbrotr.nips.nip66.geo.Nip66GeoMetadata]:
            Container that pairs this data with geolocation logs.
        [bigbrotr.nips.nip66.geo.GeoExtractor][bigbrotr.nips.nip66.geo.GeoExtractor]:
            Utility class that extracts fields from GeoIP2 City responses.
        [bigbrotr.nips.nip66.data.Nip66NetData][bigbrotr.nips.nip66.data.Nip66NetData]:
            Related network/ASN data that also relies on IP resolution.
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
    geo_hash: str | None = None
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
                "geo_hash",
            }
        ),
    )


class Nip66NetData(BaseData):
    """Network and ASN information from GeoIP ASN database lookups.

    Includes resolved IP addresses, autonomous system number and
    organization, and CIDR network ranges.

    Note:
        IPv4 ASN data takes priority; IPv6 ASN data is used as a fallback
        when IPv4 is not available. IPv6-specific network ranges are always
        recorded separately in ``net_network_v6``.

    See Also:
        [bigbrotr.nips.nip66.net.Nip66NetMetadata][bigbrotr.nips.nip66.net.Nip66NetMetadata]:
            Container that pairs this data with network lookup logs.
        [bigbrotr.nips.nip66.data.Nip66GeoData][bigbrotr.nips.nip66.data.Nip66GeoData]:
            Related geolocation data that also relies on IP resolution.
        [bigbrotr.utils.dns.resolve_host][bigbrotr.utils.dns.resolve_host]:
            DNS resolution used upstream to obtain IP addresses.
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

    Note:
        This is the comprehensive DNS data model used by the NIP-66 DNS test.
        Unlike the simpler [resolve_host][bigbrotr.utils.dns.resolve_host]
        utility (which only resolves A/AAAA), this includes CNAME, NS, PTR,
        and TTL records collected via the ``dnspython`` library.

    See Also:
        [bigbrotr.nips.nip66.dns.Nip66DnsMetadata][bigbrotr.nips.nip66.dns.Nip66DnsMetadata]:
            Container that pairs this data with DNS resolution logs.
        [bigbrotr.utils.dns.resolve_host][bigbrotr.utils.dns.resolve_host]:
            Simpler A/AAAA-only resolution used by geo and net tests.
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

    Note:
        Headers are captured using aiohttp trace hooks during the WebSocket
        upgrade handshake, not from a separate HTTP request. A non-validating
        SSL context is used to ensure headers can be captured regardless of
        certificate validity.

    See Also:
        [bigbrotr.nips.nip66.http.Nip66HttpMetadata][bigbrotr.nips.nip66.http.Nip66HttpMetadata]:
            Container that pairs this data with HTTP extraction logs.
    """

    http_server: str | None = None
    http_powered_by: str | None = None

    _FIELD_SPEC: ClassVar[FieldSpec] = FieldSpec(
        str_fields=frozenset({"http_server", "http_powered_by"}),
    )
