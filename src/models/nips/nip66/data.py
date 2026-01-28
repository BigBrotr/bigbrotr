"""NIP-66 data models."""

from __future__ import annotations

from typing import ClassVar

from pydantic import StrictBool, StrictFloat, StrictInt

from models.nips.base import BaseData


class Nip66RttData(BaseData):
    """RTT (Round-Trip Time) data per NIP-66."""

    rtt_open: StrictInt | None = None
    rtt_read: StrictInt | None = None
    rtt_write: StrictInt | None = None

    _INT_FIELDS: ClassVar[set[str]] = {"rtt_open", "rtt_read", "rtt_write"}


class Nip66SslData(BaseData):
    """SSL/TLS certificate data per NIP-66."""

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

    _BOOL_FIELDS: ClassVar[set[str]] = {"ssl_valid"}
    _INT_FIELDS: ClassVar[set[str]] = {
        "ssl_expires",
        "ssl_not_before",
        "ssl_version",
        "ssl_cipher_bits",
    }
    _STR_FIELDS: ClassVar[set[str]] = {
        "ssl_subject_cn",
        "ssl_issuer",
        "ssl_issuer_cn",
        "ssl_serial",
        "ssl_fingerprint",
        "ssl_protocol",
        "ssl_cipher",
    }
    _STR_LIST_FIELDS: ClassVar[set[str]] = {"ssl_san"}


class Nip66GeoData(BaseData):
    """Geolocation data per NIP-66."""

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

    _BOOL_FIELDS: ClassVar[set[str]] = {"geo_is_eu"}
    _INT_FIELDS: ClassVar[set[str]] = {"geo_accuracy", "geo_geoname_id"}
    _FLOAT_FIELDS: ClassVar[set[str]] = {"geo_lat", "geo_lon"}
    _STR_FIELDS: ClassVar[set[str]] = {
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


class Nip66NetData(BaseData):
    """Network/ASN data per NIP-66."""

    net_ip: str | None = None
    net_ipv6: str | None = None
    net_asn: StrictInt | None = None
    net_asn_org: str | None = None
    net_network: str | None = None
    net_network_v6: str | None = None

    _INT_FIELDS: ClassVar[set[str]] = {"net_asn"}
    _STR_FIELDS: ClassVar[set[str]] = {
        "net_ip",
        "net_ipv6",
        "net_asn_org",
        "net_network",
        "net_network_v6",
    }


class Nip66DnsData(BaseData):
    """DNS resolution data per NIP-66."""

    dns_ips: list[str] | None = None
    dns_ips_v6: list[str] | None = None
    dns_cname: str | None = None
    dns_reverse: str | None = None
    dns_ns: list[str] | None = None
    dns_ttl: StrictInt | None = None

    _INT_FIELDS: ClassVar[set[str]] = {"dns_ttl"}
    _STR_FIELDS: ClassVar[set[str]] = {"dns_cname", "dns_reverse"}
    _STR_LIST_FIELDS: ClassVar[set[str]] = {"dns_ips", "dns_ips_v6", "dns_ns"}


class Nip66HttpData(BaseData):
    """HTTP headers data per NIP-66."""

    http_server: str | None = None
    http_powered_by: str | None = None

    _STR_FIELDS: ClassVar[set[str]] = {"http_server", "http_powered_by"}
