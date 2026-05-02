"""
NIP-66 monitoring data models.

Defines the typed Pydantic models for each
[NIP-66](https://github.com/nostr-protocol/nips/blob/master/66.md) monitoring
test result: RTT (round-trip time), SSL certificate, geolocation,
network/ASN, DNS resolution, and HTTP server headers.

Note:
    All data classes extend [BaseData][bigbrotr.nips.base.BaseData] and use
    declarative [FieldSpec][bigbrotr.nips.parsing.FieldSpec] parsing with
    report-oriented issue collection under the hood. ``parse()`` returns the
    permissively parsed payload in canonical model form when field validators
    can normalize it safely, while ``parse_report()`` retains visibility into
    dropped values.
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

import re
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network
from typing import TYPE_CHECKING, Any, ClassVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, StrictBool, StrictFloat, StrictInt, field_validator

from bigbrotr.models.relay_url import _is_valid_hostname
from bigbrotr.nips.base import BaseData
from bigbrotr.nips.parsing import FieldSpec, ParseIssue, ParseReport, join_parse_path


if TYPE_CHECKING:
    from collections.abc import Callable


_GEO_LAT_MIN = -90.0
_GEO_LAT_MAX = 90.0
_GEO_LON_MIN = -180.0
_GEO_LON_MAX = 180.0
_GEO_COUNTRY_CODE_RE = re.compile(r"^[A-Z]{2}$", re.IGNORECASE)
_GEO_CONTINENT_CODES = frozenset({"AF", "AN", "AS", "EU", "NA", "OC", "SA"})
_GEOHASH_RE = re.compile(r"^[0123456789bcdefghjkmnpqrstuvwxyz]{1,12}$", re.IGNORECASE)
_SSL_SERIAL_RE = re.compile(r"^[0-9A-F]+$", re.IGNORECASE)
_SSL_FINGERPRINT_RE = re.compile(r"^SHA256:(?:[0-9A-F]{2}:){31}[0-9A-F]{2}$", re.IGNORECASE)
_SSL_PROTOCOL_CANONICAL = {
    "sslv2": "SSLv2",
    "sslv3": "SSLv3",
    "tlsv1": "TLSv1",
    "tlsv1.1": "TLSv1.1",
    "tlsv1.2": "TLSv1.2",
    "tlsv1.3": "TLSv1.3",
}
_SSL_X509_VERSIONS = frozenset({0, 2})


def _drop_negative_int_fields(
    parsed: dict[str, Any],
    issues: list[ParseIssue],
    field_names: tuple[str, ...],
    *,
    path: str,
) -> None:
    for key in field_names:
        value = parsed.get(key)
        if isinstance(value, int) and value < 0:
            del parsed[key]
            issues.append(
                ParseIssue(
                    kind="invalid_value",
                    path=join_parse_path(path, key),
                    detail="expected non-negative int",
                )
            )


def _drop_out_of_range_number_fields(
    parsed: dict[str, Any],
    issues: list[ParseIssue],
    field_ranges: tuple[tuple[str, float, float], ...],
    *,
    path: str,
) -> None:
    for key, lower, upper in field_ranges:
        value = parsed.get(key)
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and (value < lower or value > upper)
        ):
            del parsed[key]
            issues.append(
                ParseIssue(
                    kind="invalid_value",
                    path=join_parse_path(path, key),
                    detail=f"expected {lower} <= value <= {upper}",
                )
            )


def _drop_blank_string_list_entries(
    parsed: dict[str, Any],
    issues: list[ParseIssue],
    field_names: tuple[str, ...],
    *,
    path: str,
) -> None:
    for key in field_names:
        value = parsed.get(key)
        if not isinstance(value, list):
            continue

        valid_entries: list[str] = []
        for index, entry in enumerate(value):
            if entry.strip() == "":
                issues.append(
                    ParseIssue(
                        kind="invalid_value",
                        path=join_parse_path(path, f"{key}[{index}]"),
                        detail="expected non-empty str",
                    )
                )
                continue
            valid_entries.append(entry)

        if valid_entries:
            parsed[key] = sorted(set(valid_entries))
        else:
            del parsed[key]


def _drop_invalid_string_list_entries(
    parsed: dict[str, Any],
    issues: list[ParseIssue],
    field_validators: tuple[tuple[str, Callable[[str], bool], str], ...],
    *,
    path: str,
) -> None:
    for key, validator, detail in field_validators:
        value = parsed.get(key)
        if not isinstance(value, list):
            continue

        valid_entries: list[str] = []
        for index, entry in enumerate(value):
            if not validator(entry):
                issues.append(
                    ParseIssue(
                        kind="invalid_value",
                        path=join_parse_path(path, f"{key}[{index}]"),
                        detail=detail,
                    )
                )
                continue
            valid_entries.append(entry)

        if valid_entries:
            parsed[key] = sorted(set(valid_entries))
        else:
            del parsed[key]


def _drop_blank_string_fields(
    parsed: dict[str, Any],
    issues: list[ParseIssue],
    field_names: tuple[str, ...],
    *,
    path: str,
) -> None:
    for key in field_names:
        value = parsed.get(key)
        if isinstance(value, str) and value.strip() == "":
            del parsed[key]
            issues.append(
                ParseIssue(
                    kind="invalid_value",
                    path=join_parse_path(path, key),
                    detail="expected non-empty str",
                )
            )


def _drop_invalid_string_fields(
    parsed: dict[str, Any],
    issues: list[ParseIssue],
    field_validators: tuple[tuple[str, Callable[[str], bool], str], ...],
    *,
    path: str,
) -> None:
    for key, validator, detail in field_validators:
        value = parsed.get(key)
        if isinstance(value, str) and not validator(value):
            del parsed[key]
            issues.append(
                ParseIssue(
                    kind="invalid_value",
                    path=join_parse_path(path, key),
                    detail=detail,
                )
            )


def _is_valid_ipv4_address(value: str) -> bool:
    try:
        IPv4Address(value)
    except ValueError:
        return False
    return True


def _is_valid_ipv6_address(value: str) -> bool:
    try:
        IPv6Address(value)
    except ValueError:
        return False
    return True


def _canonicalize_ipv4_address(value: str) -> str:
    return str(IPv4Address(value))


def _canonicalize_ipv6_address(value: str) -> str:
    return str(IPv6Address(value))


def _is_valid_ipv4_network(value: str) -> bool:
    try:
        IPv4Network(value)
    except ValueError:
        return False
    return True


def _is_valid_ipv6_network(value: str) -> bool:
    try:
        IPv6Network(value)
    except ValueError:
        return False
    return True


def _canonicalize_ipv4_network(value: str) -> str:
    return str(IPv4Network(value))


def _canonicalize_ipv6_network(value: str) -> str:
    return str(IPv6Network(value))


def _is_valid_ssl_serial(value: str) -> bool:
    return bool(_SSL_SERIAL_RE.fullmatch(value))


def _is_valid_ssl_fingerprint(value: str) -> bool:
    return bool(_SSL_FINGERPRINT_RE.fullmatch(value))


def _normalize_ssl_protocol_name(value: str) -> str | None:
    return _SSL_PROTOCOL_CANONICAL.get(value.lower())


def _is_valid_ssl_certificate_version(value: int) -> bool:
    return value in _SSL_X509_VERSIONS


def _is_valid_geohash(value: str) -> bool:
    return bool(_GEOHASH_RE.fullmatch(value))


def _is_valid_country_code(value: str) -> bool:
    return bool(_GEO_COUNTRY_CODE_RE.fullmatch(value))


def _is_valid_continent_code(value: str) -> bool:
    return value.upper() in _GEO_CONTINENT_CODES


def _canonicalize_dns_hostname(value: str) -> str:
    return value.rstrip(".").lower()


def _is_valid_dns_hostname(value: str) -> bool:
    return _is_valid_hostname(_canonicalize_dns_hostname(value))


def _canonicalize_ssl_dns_name(value: str) -> str:
    return value.rstrip(".").lower()


def _is_valid_ssl_dns_name(value: str) -> bool:
    canonical = _canonicalize_ssl_dns_name(value)
    if canonical.startswith("*."):
        return _is_valid_hostname(canonical[2:])
    return _is_valid_hostname(canonical)


def _is_valid_timezone_name(value: str) -> bool:
    try:
        ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError):
        return False
    return True


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

    rtt_open: StrictInt | None = Field(
        default=None, description="WebSocket connection open latency in ms"
    )
    rtt_read: StrictInt | None = Field(default=None, description="Event read latency in ms")
    rtt_write: StrictInt | None = Field(default=None, description="Event write latency in ms")

    @field_validator("rtt_open", "rtt_read", "rtt_write")
    @classmethod
    def _require_non_negative_rtts(cls, value: int | None, info: Any) -> int | None:
        if value is not None and value < 0:
            raise ValueError(f"{info.field_name} must be non-negative")
        return value

    _FIELD_SPEC: ClassVar[FieldSpec] = FieldSpec(
        int_fields=frozenset({"rtt_open", "rtt_read", "rtt_write"}),
    )

    @classmethod
    def parse_report(cls, data: Any, *, path: str = "") -> ParseReport:
        """Parse RTT data while rejecting negative latency values."""
        report = super().parse_report(data, path=path)
        parsed = dict(report.parsed)
        issues = list(report.issues)
        _drop_negative_int_fields(parsed, issues, ("rtt_open", "rtt_read", "rtt_write"), path=path)
        return ParseReport(parsed=parsed, issues=tuple(issues))


class Nip66SslData(BaseData):
    """SSL/TLS certificate details extracted from a relay connection.

    Includes certificate identity, validity dates, Subject Alternative Names,
    fingerprint, and negotiated cipher information.

    Note:
        Certificate extraction uses a non-validating SSL context
        (``CERT_NONE``) to read the certificate regardless of chain validity.
        Chain validation is performed separately and recorded in ``ssl_valid``.
        The fingerprint is a SHA-256 hash of the DER-encoded certificate.
        ``ssl_san`` is normalized to a deduplicated, sorted order so
        equivalent certificate identities do not drift when extraction order
        varies.

    See Also:
        [bigbrotr.nips.nip66.ssl.Nip66SslMetadata][bigbrotr.nips.nip66.ssl.Nip66SslMetadata]:
            Container that pairs this data with SSL inspection logs.
        [bigbrotr.nips.nip66.ssl.CertificateExtractor][bigbrotr.nips.nip66.ssl.CertificateExtractor]:
            Utility class that extracts fields from Python SSL cert dicts.
    """

    ssl_valid: StrictBool | None = Field(
        default=None, description="Whether the SSL certificate chain is valid"
    )
    ssl_subject_cn: str | None = Field(default=None, description="Certificate subject common name")
    ssl_issuer: str | None = Field(default=None, description="Certificate issuer organization")
    ssl_issuer_cn: str | None = Field(default=None, description="Certificate issuer common name")
    ssl_expires: StrictInt | None = Field(
        default=None, description="Certificate expiry Unix timestamp"
    )
    ssl_not_before: StrictInt | None = Field(
        default=None, description="Certificate validity start Unix timestamp"
    )
    ssl_san: list[str] | None = Field(default=None, description="Subject Alternative Names")
    ssl_serial: str | None = Field(default=None, description="Certificate serial number")
    ssl_version: StrictInt | None = Field(default=None, description="X.509 certificate version")
    ssl_fingerprint: str | None = Field(default=None, description="SHA-256 certificate fingerprint")
    ssl_protocol: str | None = Field(default=None, description="Negotiated TLS protocol version")
    ssl_cipher: str | None = Field(default=None, description="Negotiated cipher suite")
    ssl_cipher_bits: StrictInt | None = Field(default=None, description="Cipher key size in bits")

    @field_validator("ssl_expires", "ssl_not_before", "ssl_version", "ssl_cipher_bits")
    @classmethod
    def _require_non_negative_ssl_ints(cls, value: int | None, info: Any) -> int | None:
        if value is not None and value < 0:
            raise ValueError(f"{info.field_name} must be non-negative")
        return value

    @field_validator("ssl_version")
    @classmethod
    def _normalize_ssl_certificate_version(cls, value: int | None) -> int | None:
        if value is not None and not _is_valid_ssl_certificate_version(value):
            raise ValueError("ssl_version must be a valid X.509 version enum value")
        return value

    @field_validator(
        "ssl_subject_cn",
        "ssl_issuer",
        "ssl_issuer_cn",
        "ssl_serial",
        "ssl_fingerprint",
        "ssl_protocol",
        "ssl_cipher",
    )
    @classmethod
    def _require_non_blank_ssl_strings(cls, value: str | None, info: Any) -> str | None:
        if value is not None and value.strip() == "":
            raise ValueError(f"{info.field_name} must be a non-empty string")
        return value

    @field_validator("ssl_serial")
    @classmethod
    def _normalize_ssl_serial(cls, value: str | None) -> str | None:
        if value is not None:
            if not _is_valid_ssl_serial(value):
                raise ValueError("ssl_serial must be a hexadecimal string")
            return value.upper()
        return value

    @field_validator("ssl_fingerprint")
    @classmethod
    def _normalize_ssl_fingerprint(cls, value: str | None) -> str | None:
        if value is not None:
            if not _is_valid_ssl_fingerprint(value):
                raise ValueError("ssl_fingerprint must be a SHA256 fingerprint")
            return value.upper()
        return value

    @field_validator("ssl_protocol")
    @classmethod
    def _normalize_ssl_protocol(cls, value: str | None) -> str | None:
        if value is not None:
            normalized = _normalize_ssl_protocol_name(value)
            if normalized is None:
                raise ValueError("ssl_protocol must be a valid TLS/SSL protocol version")
            return normalized
        return value

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

    @field_validator("ssl_san")
    @classmethod
    def _normalize_san_list(cls, value: list[str] | None, info: Any) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        for entry in value:
            if entry.strip() == "":
                raise ValueError(f"{info.field_name} entries must be non-empty strings")
            if not _is_valid_ssl_dns_name(entry):
                raise ValueError(f"{info.field_name} entries must be valid hostnames")
            normalized.append(_canonicalize_ssl_dns_name(entry))
        return sorted(set(normalized))

    @classmethod
    def parse_report(cls, data: Any, *, path: str = "") -> ParseReport:
        """Parse SSL data while rejecting malformed certificate metadata."""
        report = super().parse_report(data, path=path)
        parsed = dict(report.parsed)
        issues = list(report.issues)
        _drop_blank_string_fields(
            parsed,
            issues,
            (
                "ssl_subject_cn",
                "ssl_issuer",
                "ssl_issuer_cn",
                "ssl_serial",
                "ssl_fingerprint",
                "ssl_protocol",
                "ssl_cipher",
            ),
            path=path,
        )
        _drop_invalid_string_fields(
            parsed,
            issues,
            (
                ("ssl_serial", _is_valid_ssl_serial, "expected hexadecimal string"),
                ("ssl_fingerprint", _is_valid_ssl_fingerprint, "expected SHA256 fingerprint"),
                (
                    "ssl_protocol",
                    lambda value: _normalize_ssl_protocol_name(value) is not None,
                    "expected valid TLS/SSL protocol version",
                ),
            ),
            path=path,
        )
        _drop_blank_string_list_entries(parsed, issues, ("ssl_san",), path=path)
        _drop_invalid_string_list_entries(
            parsed,
            issues,
            (("ssl_san", _is_valid_ssl_dns_name, "expected valid hostname"),),
            path=path,
        )
        _drop_negative_int_fields(
            parsed,
            issues,
            ("ssl_expires", "ssl_not_before", "ssl_version", "ssl_cipher_bits"),
            path=path,
        )
        version_value = parsed.get("ssl_version")
        if isinstance(version_value, int) and not _is_valid_ssl_certificate_version(version_value):
            del parsed["ssl_version"]
            issues.append(
                ParseIssue(
                    kind="invalid_value",
                    path=join_parse_path(path, "ssl_version"),
                    detail="expected valid X.509 version enum value",
                )
            )
        return ParseReport(parsed=parsed, issues=tuple(issues))


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

    geo_country: str | None = Field(default=None, description="ISO 3166-1 alpha-2 country code")
    geo_country_name: str | None = Field(default=None, description="Country name")
    geo_continent: str | None = Field(default=None, description="Continent code")
    geo_continent_name: str | None = Field(default=None, description="Continent name")
    geo_is_eu: StrictBool | None = Field(
        default=None, description="Whether the country is in the EU"
    )
    geo_region: str | None = Field(default=None, description="Administrative region name")
    geo_city: str | None = Field(default=None, description="City name")
    geo_postal: str | None = Field(default=None, description="Postal code")
    geo_lat: StrictFloat | None = Field(default=None, description="Latitude in decimal degrees")
    geo_lon: StrictFloat | None = Field(default=None, description="Longitude in decimal degrees")
    geo_accuracy: StrictInt | None = Field(
        default=None, description="Location accuracy radius in km"
    )
    geo_tz: str | None = Field(default=None, description="IANA timezone identifier")
    geo_hash: str | None = Field(default=None, description="Geohash at configured precision")
    geo_geoname_id: StrictInt | None = Field(
        default=None, description="GeoNames location identifier"
    )

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

    @field_validator("geo_accuracy", "geo_geoname_id")
    @classmethod
    def _require_non_negative_geo_ints(cls, value: int | None, info: Any) -> int | None:
        if value is not None and value < 0:
            raise ValueError(f"{info.field_name} must be non-negative")
        return value

    @field_validator(
        "geo_country",
        "geo_country_name",
        "geo_continent",
        "geo_continent_name",
        "geo_region",
        "geo_city",
        "geo_postal",
        "geo_tz",
        "geo_hash",
    )
    @classmethod
    def _require_non_blank_geo_strings(cls, value: str | None, info: Any) -> str | None:
        if value is not None and value.strip() == "":
            raise ValueError(f"{info.field_name} must be a non-empty string")
        return value

    @field_validator("geo_country")
    @classmethod
    def _normalize_country_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _is_valid_country_code(value):
            raise ValueError("geo_country must be a valid ISO 3166-1 alpha-2 code")
        return value.upper()

    @field_validator("geo_continent")
    @classmethod
    def _normalize_continent_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _is_valid_continent_code(value):
            raise ValueError("geo_continent must be a valid continent code")
        return value.upper()

    @field_validator("geo_hash")
    @classmethod
    def _normalize_geohash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _is_valid_geohash(value):
            raise ValueError("geo_hash must be a valid geohash with precision 1 to 12")
        return value.lower()

    @field_validator("geo_tz")
    @classmethod
    def _require_valid_timezone(cls, value: str | None) -> str | None:
        if value is not None and not _is_valid_timezone_name(value):
            raise ValueError("geo_tz must be a valid IANA timezone identifier")
        return value

    @field_validator("geo_lat")
    @classmethod
    def _require_valid_latitude(cls, value: float | None) -> float | None:
        if value is not None and not _GEO_LAT_MIN <= value <= _GEO_LAT_MAX:
            raise ValueError("geo_lat must be between -90 and 90")
        return value

    @field_validator("geo_lon")
    @classmethod
    def _require_valid_longitude(cls, value: float | None) -> float | None:
        if value is not None and not _GEO_LON_MIN <= value <= _GEO_LON_MAX:
            raise ValueError("geo_lon must be between -180 and 180")
        return value

    @classmethod
    def parse_report(cls, data: Any, *, path: str = "") -> ParseReport:
        """Parse geo data while rejecting impossible numeric metadata."""
        report = super().parse_report(data, path=path)
        parsed = dict(report.parsed)
        issues = list(report.issues)
        _drop_blank_string_fields(
            parsed,
            issues,
            (
                "geo_country",
                "geo_country_name",
                "geo_continent",
                "geo_continent_name",
                "geo_region",
                "geo_city",
                "geo_postal",
                "geo_tz",
                "geo_hash",
            ),
            path=path,
        )
        _drop_invalid_string_fields(
            parsed,
            issues,
            (
                ("geo_country", _is_valid_country_code, "expected valid ISO 3166-1 alpha-2 code"),
                ("geo_continent", _is_valid_continent_code, "expected valid continent code"),
                ("geo_tz", _is_valid_timezone_name, "expected valid IANA timezone identifier"),
                ("geo_hash", _is_valid_geohash, "expected valid geohash with precision 1 to 12"),
            ),
            path=path,
        )
        _drop_negative_int_fields(parsed, issues, ("geo_accuracy", "geo_geoname_id"), path=path)
        _drop_out_of_range_number_fields(
            parsed,
            issues,
            (
                ("geo_lat", _GEO_LAT_MIN, _GEO_LAT_MAX),
                ("geo_lon", _GEO_LON_MIN, _GEO_LON_MAX),
            ),
            path=path,
        )
        return ParseReport(parsed=parsed, issues=tuple(issues))


class Nip66NetData(BaseData):
    """Network and ASN information from GeoIP ASN database lookups.

    Includes resolved IP addresses, autonomous system number and
    organization, and CIDR network ranges.

    Note:
        IPv4 ASN identity takes priority; IPv6 ASN data is used as a fallback
        when the IPv4 lookup does not identify an ASN, and may backfill
        ``net_asn_org`` only when it confirms the same ASN number.
        IPv6-specific network ranges are recorded separately in
        ``net_network_v6`` only when the IPv6 ASN lookup actually returns a
        network.

    See Also:
        [bigbrotr.nips.nip66.net.Nip66NetMetadata][bigbrotr.nips.nip66.net.Nip66NetMetadata]:
            Container that pairs this data with network lookup logs.
        [bigbrotr.nips.nip66.data.Nip66GeoData][bigbrotr.nips.nip66.data.Nip66GeoData]:
            Related geolocation data that also relies on IP resolution.
        [bigbrotr.utils.dns.resolve_host][bigbrotr.utils.dns.resolve_host]:
            DNS resolution used upstream to obtain IP addresses.
    """

    net_ip: str | None = Field(default=None, description="Resolved IPv4 address")
    net_ipv6: str | None = Field(default=None, description="Resolved IPv6 address")
    net_asn: StrictInt | None = Field(default=None, description="Autonomous System Number")
    net_asn_org: str | None = Field(default=None, description="ASN organization name")
    net_network: str | None = Field(default=None, description="IPv4 CIDR network range")
    net_network_v6: str | None = Field(default=None, description="IPv6 CIDR network range")

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

    @field_validator("net_asn")
    @classmethod
    def _require_non_negative_asn(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("net_asn must be non-negative")
        return value

    @field_validator("net_ip", "net_ipv6", "net_asn_org", "net_network", "net_network_v6")
    @classmethod
    def _require_non_blank_net_strings(cls, value: str | None, info: Any) -> str | None:
        if value is not None and value.strip() == "":
            raise ValueError(f"{info.field_name} must be a non-empty string")
        return value

    @field_validator("net_ip")
    @classmethod
    def _require_valid_ipv4_address(cls, value: str | None) -> str | None:
        if value is not None:
            if not _is_valid_ipv4_address(value):
                raise ValueError("net_ip must be a valid IPv4 address")
            return _canonicalize_ipv4_address(value)
        return value

    @field_validator("net_ipv6")
    @classmethod
    def _require_valid_ipv6_address(cls, value: str | None) -> str | None:
        if value is not None:
            if not _is_valid_ipv6_address(value):
                raise ValueError("net_ipv6 must be a valid IPv6 address")
            return _canonicalize_ipv6_address(value)
        return value

    @field_validator("net_network")
    @classmethod
    def _require_valid_ipv4_network(cls, value: str | None) -> str | None:
        if value is not None:
            if not _is_valid_ipv4_network(value):
                raise ValueError("net_network must be a valid IPv4 network")
            return _canonicalize_ipv4_network(value)
        return value

    @field_validator("net_network_v6")
    @classmethod
    def _require_valid_ipv6_network(cls, value: str | None) -> str | None:
        if value is not None:
            if not _is_valid_ipv6_network(value):
                raise ValueError("net_network_v6 must be a valid IPv6 network")
            return _canonicalize_ipv6_network(value)
        return value

    @classmethod
    def parse_report(cls, data: Any, *, path: str = "") -> ParseReport:
        """Parse network data while rejecting invalid address metadata."""
        report = super().parse_report(data, path=path)
        parsed = dict(report.parsed)
        issues = list(report.issues)
        _drop_blank_string_fields(
            parsed,
            issues,
            ("net_ip", "net_ipv6", "net_asn_org", "net_network", "net_network_v6"),
            path=path,
        )
        _drop_invalid_string_fields(
            parsed,
            issues,
            (
                ("net_ip", _is_valid_ipv4_address, "expected valid IPv4 address"),
                ("net_ipv6", _is_valid_ipv6_address, "expected valid IPv6 address"),
                ("net_network", _is_valid_ipv4_network, "expected valid IPv4 network"),
                ("net_network_v6", _is_valid_ipv6_network, "expected valid IPv6 network"),
            ),
            path=path,
        )
        _drop_negative_int_fields(parsed, issues, ("net_asn",), path=path)
        return ParseReport(parsed=parsed, issues=tuple(issues))


class Nip66DnsData(BaseData):
    """DNS resolution results for a relay hostname.

    Includes A/AAAA records, CNAME, reverse DNS (PTR), nameservers,
    and record TTL.

    Note:
        This is the comprehensive DNS data model used by the NIP-66 DNS test.
        Unlike the simpler [resolve_host][bigbrotr.utils.dns.resolve_host]
        utility (which only resolves A/AAAA), this includes CNAME, NS, PTR,
        and TTL records collected via the ``dnspython`` library. Set-like list
        fields are normalized to a deduplicated, sorted order so identical DNS
        answers do not drift when resolver iteration order changes.

    See Also:
        [bigbrotr.nips.nip66.dns.Nip66DnsMetadata][bigbrotr.nips.nip66.dns.Nip66DnsMetadata]:
            Container that pairs this data with DNS resolution logs.
        [bigbrotr.utils.dns.resolve_host][bigbrotr.utils.dns.resolve_host]:
            Simpler A/AAAA-only resolution used by geo and net tests.
    """

    dns_ips: list[str] | None = Field(default=None, description="A record IPv4 addresses")
    dns_ips_v6: list[str] | None = Field(default=None, description="AAAA record IPv6 addresses")
    dns_cname: str | None = Field(default=None, description="CNAME record target")
    dns_reverse: str | None = Field(default=None, description="PTR reverse DNS hostname")
    dns_ns: list[str] | None = Field(default=None, description="NS record nameservers")
    dns_ttl: StrictInt | None = Field(default=None, description="DNS record TTL in seconds")

    _FIELD_SPEC: ClassVar[FieldSpec] = FieldSpec(
        int_fields=frozenset({"dns_ttl"}),
        str_fields=frozenset({"dns_cname", "dns_reverse"}),
        str_list_fields=frozenset({"dns_ips", "dns_ips_v6", "dns_ns"}),
    )

    @field_validator("dns_ttl")
    @classmethod
    def _require_non_negative_ttl(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("dns_ttl must be non-negative")
        return value

    @field_validator("dns_cname", "dns_reverse")
    @classmethod
    def _require_non_blank_dns_strings(cls, value: str | None, info: Any) -> str | None:
        if value is not None and value.strip() == "":
            raise ValueError(f"{info.field_name} must be a non-empty string")
        return value

    @field_validator("dns_cname", "dns_reverse")
    @classmethod
    def _normalize_dns_hostnames(cls, value: str | None, info: Any) -> str | None:
        if value is None:
            return None
        if not _is_valid_dns_hostname(value):
            raise ValueError(f"{info.field_name} must be a valid hostname")
        return _canonicalize_dns_hostname(value)

    @field_validator("dns_ips")
    @classmethod
    def _normalize_ipv4_records(cls, value: list[str] | None, info: Any) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        for entry in value:
            if entry.strip() == "":
                raise ValueError(f"{info.field_name} entries must be non-empty strings")
            if not _is_valid_ipv4_address(entry):
                raise ValueError(f"{info.field_name} entries must be valid IPv4 addresses")
            normalized.append(_canonicalize_ipv4_address(entry))
        return sorted(set(normalized))

    @field_validator("dns_ips_v6")
    @classmethod
    def _normalize_ipv6_records(cls, value: list[str] | None, info: Any) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        for entry in value:
            if entry.strip() == "":
                raise ValueError(f"{info.field_name} entries must be non-empty strings")
            if not _is_valid_ipv6_address(entry):
                raise ValueError(f"{info.field_name} entries must be valid IPv6 addresses")
            normalized.append(_canonicalize_ipv6_address(entry))
        return sorted(set(normalized))

    @field_validator("dns_ns")
    @classmethod
    def _normalize_nameserver_lists(cls, value: list[str] | None, info: Any) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        for entry in value:
            if entry.strip() == "":
                raise ValueError(f"{info.field_name} entries must be non-empty strings")
            if not _is_valid_dns_hostname(entry):
                raise ValueError(f"{info.field_name} entries must be valid hostnames")
            normalized.append(_canonicalize_dns_hostname(entry))
        return sorted(set(normalized))

    @classmethod
    def parse_report(cls, data: Any, *, path: str = "") -> ParseReport:
        """Parse DNS data while rejecting malformed address records and TTL values."""
        report = super().parse_report(data, path=path)
        parsed = dict(report.parsed)
        issues = list(report.issues)
        _drop_blank_string_fields(parsed, issues, ("dns_cname", "dns_reverse"), path=path)
        _drop_blank_string_list_entries(
            parsed,
            issues,
            ("dns_ips", "dns_ips_v6", "dns_ns"),
            path=path,
        )
        _drop_invalid_string_list_entries(
            parsed,
            issues,
            (
                ("dns_ips", _is_valid_ipv4_address, "expected valid IPv4 address"),
                ("dns_ips_v6", _is_valid_ipv6_address, "expected valid IPv6 address"),
                ("dns_ns", _is_valid_dns_hostname, "expected valid hostname"),
            ),
            path=path,
        )
        _drop_invalid_string_fields(
            parsed,
            issues,
            (
                ("dns_cname", _is_valid_dns_hostname, "expected valid hostname"),
                ("dns_reverse", _is_valid_dns_hostname, "expected valid hostname"),
            ),
            path=path,
        )
        _drop_negative_int_fields(parsed, issues, ("dns_ttl",), path=path)
        return ParseReport(parsed=parsed, issues=tuple(issues))


class Nip66HttpData(BaseData):
    """HTTP server headers captured during WebSocket handshake.

    Records the ``Server`` and ``X-Powered-By`` response headers.

    Note:
        Headers are captured using aiohttp trace hooks during the WebSocket
        upgrade handshake, not from a separate HTTP request. Clearnet
        ``wss://`` probes keep certificate validation enabled by default and
        only switch to a non-validating SSL context when the caller explicitly
        enables insecure fallback.

    See Also:
        [bigbrotr.nips.nip66.http.Nip66HttpMetadata][bigbrotr.nips.nip66.http.Nip66HttpMetadata]:
            Container that pairs this data with HTTP extraction logs.
    """

    http_server: str | None = Field(default=None, description="Server response header value")
    http_powered_by: str | None = Field(
        default=None, description="X-Powered-By response header value"
    )

    _FIELD_SPEC: ClassVar[FieldSpec] = FieldSpec(
        str_fields=frozenset({"http_server", "http_powered_by"}),
    )

    @field_validator("http_server", "http_powered_by")
    @classmethod
    def _require_non_blank_http_strings(cls, value: str | None, info: Any) -> str | None:
        if value is not None and value.strip() == "":
            raise ValueError(f"{info.field_name} must be a non-empty string")
        return value

    @classmethod
    def parse_report(cls, data: Any, *, path: str = "") -> ParseReport:
        """Parse HTTP data while rejecting blank header strings."""
        report = super().parse_report(data, path=path)
        parsed = dict(report.parsed)
        issues = list(report.issues)
        _drop_blank_string_fields(parsed, issues, ("http_server", "http_powered_by"), path=path)
        return ParseReport(parsed=parsed, issues=tuple(issues))
