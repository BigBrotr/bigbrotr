"""
Unit tests for the ``bigbrotr.nips.nip66.data`` module.

Tests:
- Nip66RttData construction and field spec validation
- Nip66SslData construction and type filtering
- Nip66GeoData construction and type filtering
- Nip66NetData construction and type filtering
- Nip66DnsData construction with list fields
- Nip66HttpData construction
- parse() method for type sanitization
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bigbrotr.nips.nip66.data import (
    Nip66DnsData,
    Nip66GeoData,
    Nip66HttpData,
    Nip66NetData,
    Nip66RttData,
    Nip66SslData,
)


class TestNip66RttData:
    """Test Nip66RttData model."""

    def test_construction_with_all_fields(self) -> None:
        """Construct with all RTT timing values."""
        data = Nip66RttData(rtt_open=100, rtt_read=150, rtt_write=200)
        assert data.rtt_open == 100
        assert data.rtt_read == 150
        assert data.rtt_write == 200

    def test_construction_with_none_values(self) -> None:
        """Construct with None values (default)."""
        data = Nip66RttData()
        assert data.rtt_open is None
        assert data.rtt_read is None
        assert data.rtt_write is None

    def test_construction_partial_values(self) -> None:
        """Construct with partial values."""
        data = Nip66RttData(rtt_open=100)
        assert data.rtt_open == 100
        assert data.rtt_read is None
        assert data.rtt_write is None

    @pytest.mark.parametrize("kwargs", [{"rtt_open": -1}, {"rtt_read": -1}, {"rtt_write": -1}])
    def test_construction_rejects_negative_rtts(self, kwargs: dict[str, int]) -> None:
        """Constructor rejects negative RTT measurements."""
        with pytest.raises(ValidationError):
            Nip66RttData(**kwargs)

    def test_parse_filters_invalid_types(self) -> None:
        """parse() filters non-integer values for RTT fields."""
        raw = {
            "rtt_open": "fast",  # Invalid: should be int
            "rtt_read": 150,  # Valid
            "rtt_write": 200.5,  # Invalid: should be int, not float
        }
        parsed = Nip66RttData.parse(raw)
        data = Nip66RttData(**parsed)
        assert data.rtt_open is None
        assert data.rtt_read == 150
        assert data.rtt_write is None

    def test_parse_preserves_valid_ints(self) -> None:
        """parse() preserves valid integer values."""
        raw = {"rtt_open": 100, "rtt_read": 150, "rtt_write": 200}
        parsed = Nip66RttData.parse(raw)
        data = Nip66RttData(**parsed)
        assert data.rtt_open == 100
        assert data.rtt_read == 150
        assert data.rtt_write == 200

    def test_parse_filters_negative_rtts(self) -> None:
        """parse() filters negative RTT values instead of canonicalizing them."""
        raw = {"rtt_open": -1, "rtt_read": -2, "rtt_write": 200}
        parsed = Nip66RttData.parse(raw)
        assert parsed == {"rtt_write": 200}

    def test_parse_ignores_unknown_fields(self) -> None:
        """parse() ignores fields not in spec."""
        raw = {"rtt_open": 100, "unknown_field": "ignored"}
        parsed = Nip66RttData.parse(raw)
        assert "unknown_field" not in parsed
        data = Nip66RttData(**parsed)
        assert data.rtt_open == 100

    def test_parse_report_records_unknown_and_invalid_fields(self) -> None:
        """parse_report() keeps the parsed payload and records dropped RTT fields."""
        report = Nip66RttData.parse_report(
            {
                "rtt_open": 100,
                "rtt_read": "slow",
                "unknown_field": "ignored",
            }
        )

        assert report.parsed == {"rtt_open": 100}
        assert [issue.kind for issue in report.issues] == ["invalid_value", "unknown_field"]
        assert [issue.path for issue in report.issues] == ["rtt_read", "unknown_field"]

    def test_to_dict_excludes_none(self) -> None:
        """to_dict() excludes None values."""
        data = Nip66RttData(rtt_open=100)
        d = data.to_dict()
        assert d == {"rtt_open": 100}
        assert "rtt_read" not in d
        assert "rtt_write" not in d


class TestNip66SslData:
    """Test Nip66SslData model."""

    def test_construction_with_all_fields(self) -> None:
        """Construct with all SSL certificate fields."""
        data = Nip66SslData(
            ssl_valid=True,
            ssl_subject_cn="relay.example.com",
            ssl_issuer="Let's Encrypt",
            ssl_issuer_cn="R3",
            ssl_expires=1735689600,
            ssl_not_before=1727827200,
            ssl_san=["relay.example.com", "*.example.com"],
            ssl_serial="04ABCDEF",
            ssl_version=2,
            ssl_fingerprint=(
                "SHA256:AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89:"
                "AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89"
            ),
            ssl_protocol="TLSv1.3",
            ssl_cipher="TLS_AES_256_GCM_SHA384",
            ssl_cipher_bits=256,
        )
        assert data.ssl_valid is True
        assert data.ssl_subject_cn == "relay.example.com"
        assert data.ssl_issuer == "Let's Encrypt"
        assert data.ssl_cipher_bits == 256

    def test_construction_normalizes_ssl_protocol_alias_to_canonical_case(self) -> None:
        """Constructor canonicalizes valid TLS protocol names."""
        data = Nip66SslData(ssl_protocol="tlsv1.3")
        assert data.ssl_protocol == "TLSv1.3"

    def test_construction_normalizes_san_list(self) -> None:
        """Constructor deduplicates and sorts SAN values."""
        data = Nip66SslData(
            ssl_san=[
                "RELAY.EXAMPLE.COM.",
                "*.EXAMPLE.COM.",
                "relay.example.com",
            ],
        )
        assert data.ssl_san == ["*.example.com", "relay.example.com"]

    def test_construction_rejects_blank_san_entries(self) -> None:
        """Constructor rejects blank or whitespace-only SAN entries."""
        with pytest.raises(ValidationError, match="ssl_san entries must be non-empty strings"):
            Nip66SslData(ssl_san=[" ", "relay.example.com"])

    @pytest.mark.parametrize(
        ("value", "message"),
        [
            (["singlehost", "*.example.com"], "ssl_san entries must be valid hostnames"),
            (["*.singlehost"], "ssl_san entries must be valid hostnames"),
            (["*.*.example.com"], "ssl_san entries must be valid hostnames"),
        ],
    )
    def test_construction_rejects_invalid_san_entries(self, value: list[str], message: str) -> None:
        """Constructor rejects malformed DNS SAN values."""
        with pytest.raises(ValidationError, match=message):
            Nip66SslData(ssl_san=value)

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"ssl_subject_cn": " "}, "ssl_subject_cn must be a non-empty string"),
            ({"ssl_issuer": ""}, "ssl_issuer must be a non-empty string"),
            ({"ssl_issuer_cn": " "}, "ssl_issuer_cn must be a non-empty string"),
            ({"ssl_serial": ""}, "ssl_serial must be a non-empty string"),
            ({"ssl_fingerprint": " "}, "ssl_fingerprint must be a non-empty string"),
            ({"ssl_protocol": ""}, "ssl_protocol must be a non-empty string"),
            ({"ssl_cipher": " "}, "ssl_cipher must be a non-empty string"),
        ],
    )
    def test_construction_rejects_blank_scalar_ssl_strings(
        self, kwargs: dict[str, str], message: str
    ) -> None:
        """Constructor rejects blank or whitespace-only scalar SSL strings."""
        with pytest.raises(ValidationError, match=message):
            Nip66SslData(**kwargs)

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"ssl_serial": "not-hex"}, "ssl_serial must be a hexadecimal string"),
            ({"ssl_serial": "0xABCD"}, "ssl_serial must be a hexadecimal string"),
            ({"ssl_fingerprint": "bad"}, "ssl_fingerprint must be a SHA256 fingerprint"),
            (
                {"ssl_fingerprint": "SHA1:AB:CD"},
                "ssl_fingerprint must be a SHA256 fingerprint",
            ),
        ],
    )
    def test_construction_rejects_invalid_ssl_identifiers(
        self, kwargs: dict[str, str], message: str
    ) -> None:
        """Constructor rejects malformed SSL serial and fingerprint values."""
        with pytest.raises(ValidationError, match=message):
            Nip66SslData(**kwargs)

    @pytest.mark.parametrize("value", ["TLS1.3", "DTLSv1.2", "bogus"])
    def test_construction_rejects_invalid_ssl_protocol(self, value: str) -> None:
        """Constructor rejects malformed TLS protocol names."""
        with pytest.raises(
            ValidationError, match="ssl_protocol must be a valid TLS/SSL protocol version"
        ):
            Nip66SslData(ssl_protocol=value)

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"ssl_expires": -1},
            {"ssl_not_before": -1},
            {"ssl_version": -1},
            {"ssl_cipher_bits": -1},
        ],
    )
    def test_construction_rejects_negative_ssl_ints(self, kwargs: dict[str, int]) -> None:
        """Constructor rejects negative numeric SSL metadata."""
        with pytest.raises(ValidationError):
            Nip66SslData(**kwargs)

    @pytest.mark.parametrize("value", [1, 3, 4])
    def test_construction_rejects_invalid_ssl_version(self, value: int) -> None:
        """Constructor rejects values outside the X.509 version enum domain."""
        with pytest.raises(
            ValidationError, match=r"ssl_version must be a valid X\.509 version enum value"
        ):
            Nip66SslData(ssl_version=value)

    def test_parse_filters_invalid_bool(self) -> None:
        """parse() filters invalid boolean values."""
        raw = {
            "ssl_valid": "yes",  # Invalid: should be bool
            "ssl_issuer": "Test CA",  # Valid
        }
        parsed = Nip66SslData.parse(raw)
        data = Nip66SslData(**parsed)
        assert data.ssl_valid is None
        assert data.ssl_issuer == "Test CA"

    def test_parse_filters_invalid_int_types(self) -> None:
        """parse() filters invalid integer values."""
        raw = {
            "ssl_expires": "tomorrow",  # Invalid: should be int
            "ssl_version": 2,  # Valid
            "ssl_cipher_bits": "256",  # Invalid: string, not int
        }
        parsed = Nip66SslData.parse(raw)
        data = Nip66SslData(**parsed)
        assert data.ssl_expires is None
        assert data.ssl_version == 2
        assert data.ssl_cipher_bits is None

    def test_parse_filters_negative_ssl_ints(self) -> None:
        """parse() filters negative numeric SSL metadata."""
        raw = {
            "ssl_valid": True,
            "ssl_expires": -1,
            "ssl_not_before": -2,
            "ssl_version": -3,
            "ssl_cipher_bits": -4,
        }
        parsed = Nip66SslData.parse(raw)
        assert parsed == {"ssl_valid": True}

    def test_parse_filters_invalid_str_types(self) -> None:
        """parse() filters invalid string values."""
        raw = {
            "ssl_issuer": 123,  # Invalid: should be str
            "ssl_protocol": "TLSv1.3",  # Valid
        }
        parsed = Nip66SslData.parse(raw)
        data = Nip66SslData(**parsed)
        assert data.ssl_issuer is None
        assert data.ssl_protocol == "TLSv1.3"

    def test_parse_handles_san_list(self) -> None:
        """parse() normalizes valid SAN lists."""
        raw = {
            "ssl_san": [
                "RELAY.EXAMPLE.COM.",
                "*.EXAMPLE.COM.",
                "relay.example.com",
            ]
        }
        parsed = Nip66SslData.parse(raw)
        assert parsed == {"ssl_san": ["*.example.com", "relay.example.com"]}

    def test_parse_filters_empty_san_list(self) -> None:
        """parse() filters empty SAN list."""
        raw = {"ssl_san": []}
        parsed = Nip66SslData.parse(raw)
        data = Nip66SslData(**parsed)
        assert data.ssl_san is None

    def test_parse_filters_invalid_san_elements(self) -> None:
        """parse() filters invalid elements in SAN list."""
        raw = {
            "ssl_san": [
                "RELAY.EXAMPLE.COM",
                123,
                None,
                "*.EXAMPLE.COM",
                "singlehost",
                "relay.example.com",
            ]
        }
        parsed = Nip66SslData.parse(raw)
        assert parsed == {"ssl_san": ["*.example.com", "relay.example.com"]}

    def test_parse_filters_blank_san_entries(self) -> None:
        """parse() filters blank or whitespace-only SAN entries."""
        raw = {"ssl_san": [" ", "relay.example.com", "", "*.example.com"]}
        parsed = Nip66SslData.parse(raw)
        assert parsed == {"ssl_san": ["*.example.com", "relay.example.com"]}

    def test_parse_filters_blank_scalar_ssl_strings(self) -> None:
        """parse() filters blank or whitespace-only scalar SSL strings."""
        raw = {
            "ssl_issuer": " ",
            "ssl_protocol": "TLSv1.3",
            "ssl_cipher": "",
        }
        parsed = Nip66SslData.parse(raw)
        assert parsed == {"ssl_protocol": "TLSv1.3"}

    def test_parse_filters_invalid_ssl_identifiers(self) -> None:
        """parse() filters malformed SSL serial and fingerprint values."""
        raw = {
            "ssl_serial": "not-hex",
            "ssl_fingerprint": "bad",
            "ssl_protocol": "TLSv1.3",
        }
        parsed = Nip66SslData.parse(raw)
        assert parsed == {"ssl_protocol": "TLSv1.3"}

    def test_parse_normalizes_ssl_protocol_alias_to_canonical_case(self) -> None:
        """parse() preserves valid TLS protocol names in canonical case."""
        raw = {"ssl_protocol": "tlsv1.2"}
        parsed = Nip66SslData.parse(raw)
        assert parsed == {"ssl_protocol": "TLSv1.2"}

    def test_parse_filters_invalid_ssl_protocol(self) -> None:
        """parse() filters malformed TLS protocol names."""
        raw = {"ssl_protocol": "TLS1.3", "ssl_cipher": "TLS_AES_256_GCM_SHA384"}
        parsed = Nip66SslData.parse(raw)
        assert parsed == {"ssl_cipher": "TLS_AES_256_GCM_SHA384"}

    def test_parse_filters_invalid_ssl_version(self) -> None:
        """parse() filters X.509 version integers outside the enum domain."""
        raw = {"ssl_version": 3, "ssl_protocol": "TLSv1.3"}
        parsed = Nip66SslData.parse(raw)
        assert parsed == {"ssl_protocol": "TLSv1.3"}


class TestNip66GeoData:
    """Test Nip66GeoData model."""

    def test_construction_with_all_fields(self) -> None:
        """Construct with all geo location fields."""
        data = Nip66GeoData(
            geo_country="US",
            geo_country_name="United States",
            geo_continent="NA",
            geo_continent_name="North America",
            geo_is_eu=False,
            geo_region="California",
            geo_city="Mountain View",
            geo_postal="94035",
            geo_lat=37.386,
            geo_lon=-122.084,
            geo_accuracy=10,
            geo_tz="America/Los_Angeles",
            geo_hash="9q9hvu7wp",
            geo_geoname_id=5375480,
        )
        assert data.geo_country == "US"
        assert data.geo_lat == 37.386
        assert data.geo_is_eu is False
        assert data.geo_geoname_id == 5375480

    def test_construction_normalizes_geohash_to_lowercase(self) -> None:
        """Constructor canonicalizes valid geohash strings to lowercase."""
        data = Nip66GeoData(geo_hash="U33DC")
        assert data.geo_hash == "u33dc"

    def test_construction_normalizes_geo_codes_to_uppercase(self) -> None:
        """Constructor canonicalizes valid country and continent codes to uppercase."""
        data = Nip66GeoData(geo_country="us", geo_continent="eu")
        assert data.geo_country == "US"
        assert data.geo_continent == "EU"

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"geo_country": " "}, "geo_country must be a non-empty string"),
            ({"geo_country_name": ""}, "geo_country_name must be a non-empty string"),
            ({"geo_continent": " "}, "geo_continent must be a non-empty string"),
            ({"geo_continent_name": ""}, "geo_continent_name must be a non-empty string"),
            ({"geo_region": " "}, "geo_region must be a non-empty string"),
            ({"geo_city": ""}, "geo_city must be a non-empty string"),
            ({"geo_postal": " "}, "geo_postal must be a non-empty string"),
            ({"geo_tz": ""}, "geo_tz must be a non-empty string"),
            ({"geo_hash": " "}, "geo_hash must be a non-empty string"),
        ],
    )
    def test_construction_rejects_blank_scalar_geo_strings(
        self, kwargs: dict[str, str], message: str
    ) -> None:
        """Constructor rejects blank or whitespace-only scalar geo strings."""
        with pytest.raises(ValidationError, match=message):
            Nip66GeoData(**kwargs)

    @pytest.mark.parametrize("value", ["abc", "u33dc!", "u33dc12345678"])
    def test_construction_rejects_invalid_geohashes(self, value: str) -> None:
        """Constructor rejects malformed geohash strings."""
        with pytest.raises(
            ValidationError, match="geo_hash must be a valid geohash with precision 1 to 12"
        ):
            Nip66GeoData(geo_hash=value)

    def test_construction_rejects_invalid_timezone_identifier(self) -> None:
        """Constructor rejects malformed IANA timezone identifiers."""
        with pytest.raises(
            ValidationError, match="geo_tz must be a valid IANA timezone identifier"
        ):
            Nip66GeoData(geo_tz="Mars/Phobos")

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"geo_country": "USA"}, "geo_country must be a valid ISO 3166-1 alpha-2 code"),
            ({"geo_country": "U1"}, "geo_country must be a valid ISO 3166-1 alpha-2 code"),
            ({"geo_continent": "ZZ"}, "geo_continent must be a valid continent code"),
            ({"geo_continent": "1"}, "geo_continent must be a valid continent code"),
        ],
    )
    def test_construction_rejects_invalid_geo_codes(
        self, kwargs: dict[str, str], message: str
    ) -> None:
        """Constructor rejects malformed country and continent codes."""
        with pytest.raises(ValidationError, match=message):
            Nip66GeoData(**kwargs)

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"geo_lat": 91.0}, "geo_lat must be between -90 and 90"),
            ({"geo_lat": -91.0}, "geo_lat must be between -90 and 90"),
            ({"geo_lon": 181.0}, "geo_lon must be between -180 and 180"),
            ({"geo_lon": -181.0}, "geo_lon must be between -180 and 180"),
        ],
    )
    def test_construction_rejects_out_of_range_coordinates(
        self, kwargs: dict[str, float], message: str
    ) -> None:
        """Constructor rejects latitude/longitude values outside Earth bounds."""
        with pytest.raises(ValidationError, match=message):
            Nip66GeoData(**kwargs)

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"geo_accuracy": -1},
            {"geo_geoname_id": -1},
        ],
    )
    def test_construction_rejects_negative_geo_ints(self, kwargs: dict[str, int]) -> None:
        """Constructor rejects negative integer geo metadata."""
        with pytest.raises(ValidationError):
            Nip66GeoData(**kwargs)

    def test_parse_filters_invalid_float_types(self) -> None:
        """parse() filters invalid float values."""
        raw = {
            "geo_lat": "37.386",  # Invalid: string, not float
            "geo_lon": -122.084,  # Valid
        }
        parsed = Nip66GeoData.parse(raw)
        data = Nip66GeoData(**parsed)
        assert data.geo_lat is None
        assert data.geo_lon == -122.084

    def test_parse_filters_non_finite_float_values(self) -> None:
        """parse() filters NaN and infinity for geo coordinates."""
        raw = {
            "geo_country": "US",  # Valid
            "geo_lat": float("nan"),  # Invalid: non-finite float
            "geo_lon": float("inf"),  # Invalid: non-finite float
        }
        parsed = Nip66GeoData.parse(raw)
        data = Nip66GeoData(**parsed)
        assert data.geo_country == "US"
        assert data.geo_lat is None
        assert data.geo_lon is None

    def test_parse_filters_out_of_range_coordinates(self) -> None:
        """parse() filters latitude/longitude values outside Earth bounds."""
        raw = {
            "geo_country": "US",
            "geo_lat": 95.0,
            "geo_lon": 200.0,
        }
        parsed = Nip66GeoData.parse(raw)
        assert parsed == {"geo_country": "US"}

    def test_parse_filters_invalid_geohash(self) -> None:
        """parse() filters malformed geohash strings."""
        raw = {
            "geo_country": "US",
            "geo_hash": "abc",
        }
        parsed = Nip66GeoData.parse(raw)
        assert parsed == {"geo_country": "US"}

    def test_parse_normalizes_geohash_to_lowercase(self) -> None:
        """parse() preserves valid geohash values in canonical lowercase form."""
        raw = {
            "geo_hash": "U33DC",
        }
        parsed = Nip66GeoData.parse(raw)
        data = Nip66GeoData(**parsed)
        assert data.geo_hash == "u33dc"

    def test_parse_normalizes_geo_codes_to_uppercase(self) -> None:
        """parse() preserves valid country and continent codes in canonical uppercase form."""
        raw = {
            "geo_country": "us",
            "geo_continent": "eu",
        }
        parsed = Nip66GeoData.parse(raw)
        data = Nip66GeoData(**parsed)
        assert data.geo_country == "US"
        assert data.geo_continent == "EU"

    def test_parse_filters_invalid_timezone_identifier(self) -> None:
        """parse() filters malformed IANA timezone identifiers."""
        raw = {
            "geo_country": "US",
            "geo_tz": "Mars/Phobos",
        }
        parsed = Nip66GeoData.parse(raw)
        assert parsed == {"geo_country": "US"}

    def test_parse_filters_invalid_geo_codes(self) -> None:
        """parse() filters malformed country and continent codes."""
        raw = {
            "geo_country": "USA",
            "geo_continent": "ZZ",
            "geo_country_name": "United States",
        }
        parsed = Nip66GeoData.parse(raw)
        assert parsed == {"geo_country_name": "United States"}

    def test_parse_filters_invalid_bool_types(self) -> None:
        """parse() filters invalid boolean values."""
        raw = {
            "geo_is_eu": "no",  # Invalid: string, not bool
            "geo_country": "US",  # Valid
        }
        parsed = Nip66GeoData.parse(raw)
        data = Nip66GeoData(**parsed)
        assert data.geo_is_eu is None
        assert data.geo_country == "US"

    def test_parse_filters_invalid_int_types(self) -> None:
        """parse() filters invalid integer values."""
        raw = {
            "geo_accuracy": 10.5,  # Invalid: float, not int
            "geo_geoname_id": "5375480",  # Invalid: string, not int
        }
        parsed = Nip66GeoData.parse(raw)
        data = Nip66GeoData(**parsed)
        assert data.geo_accuracy is None
        assert data.geo_geoname_id is None

    def test_parse_filters_negative_geo_ints(self) -> None:
        """parse() filters negative integer geo metadata."""
        raw = {"geo_accuracy": -1, "geo_geoname_id": -2, "geo_country": "US"}
        parsed = Nip66GeoData.parse(raw)
        assert parsed == {"geo_country": "US"}

    def test_parse_filters_blank_scalar_geo_strings(self) -> None:
        """parse() filters blank or whitespace-only scalar geo strings."""
        raw = {
            "geo_country": "US",
            "geo_city": " ",
            "geo_tz": "",
        }
        parsed = Nip66GeoData.parse(raw)
        assert parsed == {"geo_country": "US"}


class TestNip66NetData:
    """Test Nip66NetData model."""

    def test_construction_with_all_fields(self) -> None:
        """Construct with all network/ASN fields."""
        data = Nip66NetData(
            net_ip="8.8.8.8",
            net_ipv6="2001:4860:4860::8888",
            net_asn=15169,
            net_asn_org="GOOGLE",
            net_network="8.8.8.0/24",
            net_network_v6="2001:4860::/32",
        )
        assert data.net_ip == "8.8.8.8"
        assert data.net_asn == 15169
        assert data.net_network_v6 == "2001:4860::/32"

    def test_construction_canonicalizes_ipv6_net_fields(self) -> None:
        """Constructor canonicalizes equivalent IPv6 address and network strings."""
        data = Nip66NetData(
            net_ipv6="2001:DB8:0:0:0:0:0:1",
            net_network_v6="2001:DB8:0:0::/32",
        )

        assert data.net_ipv6 == "2001:db8::1"
        assert data.net_network_v6 == "2001:db8::/32"

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"net_ip": " "}, "net_ip must be a non-empty string"),
            ({"net_ipv6": ""}, "net_ipv6 must be a non-empty string"),
            ({"net_asn_org": " "}, "net_asn_org must be a non-empty string"),
            ({"net_network": ""}, "net_network must be a non-empty string"),
            ({"net_network_v6": " "}, "net_network_v6 must be a non-empty string"),
        ],
    )
    def test_construction_rejects_blank_scalar_net_strings(
        self, kwargs: dict[str, str], message: str
    ) -> None:
        """Constructor rejects blank or whitespace-only scalar net strings."""
        with pytest.raises(ValidationError, match=message):
            Nip66NetData(**kwargs)

    def test_construction_rejects_negative_asn(self) -> None:
        """Constructor rejects negative ASN values."""
        with pytest.raises(ValidationError):
            Nip66NetData(net_asn=-1)

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"net_ip": "not-an-ip"}, "net_ip must be a valid IPv4 address"),
            ({"net_ip": "2001:4860:4860::8888"}, "net_ip must be a valid IPv4 address"),
            ({"net_ipv6": "not-an-ipv6"}, "net_ipv6 must be a valid IPv6 address"),
            ({"net_ipv6": "8.8.8.8"}, "net_ipv6 must be a valid IPv6 address"),
            ({"net_network": "bad-cidr"}, "net_network must be a valid IPv4 network"),
            ({"net_network": "2001:4860::/32"}, "net_network must be a valid IPv4 network"),
            ({"net_network_v6": "bad-v6-cidr"}, "net_network_v6 must be a valid IPv6 network"),
            ({"net_network_v6": "8.8.8.0/24"}, "net_network_v6 must be a valid IPv6 network"),
        ],
    )
    def test_construction_rejects_invalid_network_address_strings(
        self, kwargs: dict[str, str], message: str
    ) -> None:
        """Constructor rejects malformed IP address and CIDR strings."""
        with pytest.raises(ValidationError, match=message):
            Nip66NetData(**kwargs)

    def test_parse_filters_invalid_ip_types(self) -> None:
        """parse() filters invalid IP string types."""
        raw = {
            "net_ip": 127001,  # Invalid: int, not str
            "net_ipv6": "2001:4860:4860::8888",  # Valid
        }
        parsed = Nip66NetData.parse(raw)
        data = Nip66NetData(**parsed)
        assert data.net_ip is None
        assert data.net_ipv6 == "2001:4860:4860::8888"

    def test_parse_filters_invalid_asn_types(self) -> None:
        """parse() filters invalid ASN types."""
        raw = {
            "net_asn": "15169",  # Invalid: string, not int
            "net_asn_org": "GOOGLE",  # Valid
        }
        parsed = Nip66NetData.parse(raw)
        data = Nip66NetData(**parsed)
        assert data.net_asn is None
        assert data.net_asn_org == "GOOGLE"

    def test_parse_filters_negative_asn(self) -> None:
        """parse() filters negative ASN values."""
        raw = {"net_asn": -1, "net_asn_org": "GOOGLE"}
        parsed = Nip66NetData.parse(raw)
        assert parsed == {"net_asn_org": "GOOGLE"}

    def test_parse_filters_blank_scalar_net_strings(self) -> None:
        """parse() filters blank or whitespace-only scalar net strings."""
        raw = {
            "net_asn": 15169,
            "net_asn_org": " ",
            "net_network": "",
        }
        parsed = Nip66NetData.parse(raw)
        assert parsed == {"net_asn": 15169}

    def test_parse_filters_invalid_network_address_strings(self) -> None:
        """parse() filters malformed IP address and CIDR strings."""
        raw = {
            "net_ip": "not-an-ip",
            "net_ipv6": "8.8.8.8",
            "net_asn": 15169,
            "net_asn_org": "GOOGLE",
            "net_network": "2001:4860::/32",
            "net_network_v6": "8.8.8.0/24",
        }
        parsed = Nip66NetData.parse(raw)
        assert parsed == {"net_asn": 15169, "net_asn_org": "GOOGLE"}

    def test_parse_canonicalizes_ipv6_net_fields(self) -> None:
        """parse() canonicalizes equivalent IPv6 address and network strings."""
        raw = {
            "net_ipv6": "2001:DB8:0:0:0:0:0:1",
            "net_network_v6": "2001:DB8:0:0::/32",
        }
        parsed = Nip66NetData.parse(raw)
        assert parsed == {
            "net_ipv6": "2001:db8::1",
            "net_network_v6": "2001:db8::/32",
        }


class TestNip66DnsData:
    """Test Nip66DnsData model."""

    def test_construction_with_all_fields(self) -> None:
        """Construct with all DNS record fields."""
        data = Nip66DnsData(
            dns_ips=["8.8.8.8", "8.8.4.4"],
            dns_ips_v6=["2001:4860:4860::8888"],
            dns_cname="dns.google",
            dns_reverse="dns.google",
            dns_ns=["ns1.google.com", "ns2.google.com"],
            dns_ttl=300,
        )
        assert data.dns_ips == ["8.8.4.4", "8.8.8.8"]
        assert data.dns_ttl == 300
        assert len(data.dns_ns) == 2

    def test_construction_rejects_negative_ttl(self) -> None:
        """Constructor rejects negative DNS TTL values."""
        with pytest.raises(ValidationError):
            Nip66DnsData(dns_ttl=-1)

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"dns_cname": ""}, "dns_cname must be a non-empty string"),
            ({"dns_reverse": " "}, "dns_reverse must be a non-empty string"),
        ],
    )
    def test_construction_rejects_blank_scalar_dns_strings(
        self, kwargs: dict[str, str], message: str
    ) -> None:
        """Constructor rejects blank or whitespace-only scalar DNS strings."""
        with pytest.raises(ValidationError, match=message):
            Nip66DnsData(**kwargs)

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"dns_ips": ["not-an-ip", "8.8.8.8"]}, "dns_ips entries must be valid IPv4 addresses"),
            (
                {"dns_ips": ["2001:4860:4860::8888"]},
                "dns_ips entries must be valid IPv4 addresses",
            ),
            (
                {"dns_ips_v6": ["not-an-ipv6", "2001:4860:4860::8888"]},
                "dns_ips_v6 entries must be valid IPv6 addresses",
            ),
            ({"dns_ips_v6": ["8.8.8.8"]}, "dns_ips_v6 entries must be valid IPv6 addresses"),
        ],
    )
    def test_construction_rejects_invalid_dns_address_entries(
        self, kwargs: dict[str, list[str]], message: str
    ) -> None:
        """Constructor rejects malformed A and AAAA record strings."""
        with pytest.raises(ValidationError, match=message):
            Nip66DnsData(**kwargs)

    def test_construction_normalizes_set_like_dns_lists(self) -> None:
        """Constructed DNS set-like lists are deduplicated and sorted."""
        data = Nip66DnsData(
            dns_ips=["8.8.4.4", "8.8.8.8", "8.8.4.4"],
            dns_ips_v6=["2001:4860:4860::8844", "2001:4860:4860::8888", "2001:4860:4860::8844"],
            dns_ns=["NS2.GOOGLE.COM", "ns1.google.com", "NS2.GOOGLE.COM"],
        )

        assert data.dns_ips == ["8.8.4.4", "8.8.8.8"]
        assert data.dns_ips_v6 == ["2001:4860:4860::8844", "2001:4860:4860::8888"]
        assert data.dns_ns == ["ns1.google.com", "ns2.google.com"]

    def test_construction_canonicalizes_ipv6_dns_records(self) -> None:
        """Constructor canonicalizes equivalent IPv6 AAAA records before deduping."""
        data = Nip66DnsData(
            dns_ips_v6=["2001:DB8:0:0:0:0:0:1", "2001:db8::1"],
        )

        assert data.dns_ips_v6 == ["2001:db8::1"]

    def test_construction_normalizes_scalar_dns_hostnames_to_canonical_form(self) -> None:
        """Constructor canonicalizes scalar DNS hostnames to lowercase without trailing dots."""
        data = Nip66DnsData(dns_cname="DNS.GOOGLE.", dns_reverse="PTR.EXAMPLE.COM.")
        assert data.dns_cname == "dns.google"
        assert data.dns_reverse == "ptr.example.com"

    def test_construction_normalizes_nameserver_fqdns_to_canonical_form(self) -> None:
        """Constructor canonicalizes NS entries to lowercase without trailing dots."""
        data = Nip66DnsData(dns_ns=["NS2.GOOGLE.COM.", "ns1.google.com."])
        assert data.dns_ns == ["ns1.google.com", "ns2.google.com"]

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"dns_ips": ["", "8.8.8.8"]}, "dns_ips entries must be non-empty strings"),
            (
                {"dns_ips_v6": [" ", "2001:4860:4860::8888"]},
                "dns_ips_v6 entries must be non-empty strings",
            ),
            ({"dns_ns": [" ", "ns1.google.com"]}, "dns_ns entries must be non-empty strings"),
        ],
    )
    def test_construction_rejects_blank_dns_list_entries(
        self, kwargs: dict[str, list[str]], message: str
    ) -> None:
        """Constructor rejects blank or whitespace-only DNS list entries."""
        with pytest.raises(ValidationError, match=message):
            Nip66DnsData(**kwargs)

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"dns_cname": "singlehost"}, "dns_cname must be a valid hostname"),
            ({"dns_reverse": "-bad.example"}, "dns_reverse must be a valid hostname"),
            (
                {"dns_ns": ["singlehost", "ns1.google.com"]},
                "dns_ns entries must be valid hostnames",
            ),
        ],
    )
    def test_construction_rejects_invalid_dns_hostnames(
        self, kwargs: dict[str, object], message: str
    ) -> None:
        """Constructor rejects malformed DNS hostname fields."""
        with pytest.raises(ValidationError, match=message):
            Nip66DnsData(**kwargs)

    def test_parse_filters_empty_lists(self) -> None:
        """parse() filters empty lists."""
        raw = {
            "dns_ips": [],  # Empty list
            "dns_ttl": 300,  # Valid
        }
        parsed = Nip66DnsData.parse(raw)
        data = Nip66DnsData(**parsed)
        assert data.dns_ips is None
        assert data.dns_ttl == 300

    def test_parse_filters_invalid_list_elements(self) -> None:
        """parse() filters invalid elements in lists."""
        raw = {
            "dns_ips": ["8.8.8.8", 123, None, "8.8.4.4", "8.8.8.8"],
            "dns_ns": ["ns2.google.com", 456, "ns1.google.com", "ns2.google.com"],
        }
        parsed = Nip66DnsData.parse(raw)
        assert parsed == {
            "dns_ips": ["8.8.4.4", "8.8.8.8"],
            "dns_ns": ["ns1.google.com", "ns2.google.com"],
        }

    def test_parse_filters_blank_dns_list_entries(self) -> None:
        """parse() filters blank or whitespace-only DNS list entries."""
        raw = {
            "dns_ips": [" ", "8.8.8.8", ""],
            "dns_ips_v6": ["", "2001:4860:4860::8888", " "],
            "dns_ns": [" ", "ns1.google.com", ""],
        }
        parsed = Nip66DnsData.parse(raw)
        assert parsed == {
            "dns_ips": ["8.8.8.8"],
            "dns_ips_v6": ["2001:4860:4860::8888"],
            "dns_ns": ["ns1.google.com"],
        }

    def test_parse_filters_invalid_dns_address_entries(self) -> None:
        """parse() filters malformed A and AAAA record strings."""
        raw = {
            "dns_ips": ["not-an-ip", "8.8.8.8", "2001:4860:4860::8888"],
            "dns_ips_v6": ["bad-v6", "2001:4860:4860::8888", "8.8.8.8"],
            "dns_ns": ["ns1.google.com"],
        }
        parsed = Nip66DnsData.parse(raw)
        assert parsed == {
            "dns_ips": ["8.8.8.8"],
            "dns_ips_v6": ["2001:4860:4860::8888"],
            "dns_ns": ["ns1.google.com"],
        }

    def test_parse_canonicalizes_ipv6_dns_records(self) -> None:
        """parse() canonicalizes equivalent IPv6 AAAA records before deduping."""
        raw = {
            "dns_ips_v6": ["2001:DB8:0:0:0:0:0:1", "2001:db8::1"],
        }
        parsed = Nip66DnsData.parse(raw)
        assert parsed == {"dns_ips_v6": ["2001:db8::1"]}

    def test_parse_filters_invalid_dns_hostnames(self) -> None:
        """parse() filters malformed DNS hostname fields."""
        raw = {
            "dns_cname": "singlehost",
            "dns_reverse": "-bad.example",
            "dns_ns": ["singlehost", "ns1.google.com"],
            "dns_ttl": 300,
        }
        parsed = Nip66DnsData.parse(raw)
        assert parsed == {"dns_ns": ["ns1.google.com"], "dns_ttl": 300}

    def test_parse_normalizes_dns_hostnames_to_canonical_form(self) -> None:
        """parse() preserves valid DNS hostname fields in lowercase without trailing dots."""
        raw = {
            "dns_cname": "DNS.GOOGLE.",
            "dns_reverse": "PTR.EXAMPLE.COM.",
            "dns_ns": ["NS2.GOOGLE.COM.", "ns1.google.com."],
        }
        parsed = Nip66DnsData.parse(raw)
        data = Nip66DnsData(**parsed)
        assert data.dns_cname == "dns.google"
        assert data.dns_reverse == "ptr.example.com"
        assert data.dns_ns == ["ns1.google.com", "ns2.google.com"]

    def test_parse_filters_blank_scalar_dns_strings(self) -> None:
        """parse() filters blank or whitespace-only scalar DNS strings."""
        raw = {
            "dns_cname": "",
            "dns_reverse": " ",
            "dns_ttl": 300,
        }
        parsed = Nip66DnsData.parse(raw)
        assert parsed == {"dns_ttl": 300}

    def test_parse_list_all_invalid_becomes_none(self) -> None:
        """parse() returns None when list has only invalid elements."""
        raw = {
            "dns_ips": [123, 456, 789],  # All invalid
            "dns_ns": [None, None],  # All None
        }
        parsed = Nip66DnsData.parse(raw)
        data = Nip66DnsData(**parsed)
        assert data.dns_ips is None
        assert data.dns_ns is None

    def test_parse_filters_negative_ttl(self) -> None:
        """parse() filters negative DNS TTL values."""
        raw = {"dns_ttl": -1, "dns_cname": "dns.google"}
        parsed = Nip66DnsData.parse(raw)
        assert parsed == {"dns_cname": "dns.google"}


class TestNip66HttpData:
    """Test Nip66HttpData model."""

    def test_construction_with_all_fields(self) -> None:
        """Construct with all HTTP header fields."""
        data = Nip66HttpData(
            http_server="nginx/1.24.0",
            http_powered_by="Strfry",
        )
        assert data.http_server == "nginx/1.24.0"
        assert data.http_powered_by == "Strfry"

    def test_construction_with_none_values(self) -> None:
        """Construct with None values (default)."""
        data = Nip66HttpData()
        assert data.http_server is None
        assert data.http_powered_by is None

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"http_server": ""}, "http_server must be a non-empty string"),
            ({"http_powered_by": " "}, "http_powered_by must be a non-empty string"),
        ],
    )
    def test_construction_rejects_blank_http_strings(
        self, kwargs: dict[str, str], message: str
    ) -> None:
        """Constructor rejects blank or whitespace-only HTTP header strings."""
        with pytest.raises(ValidationError, match=message):
            Nip66HttpData(**kwargs)

    def test_parse_filters_invalid_types(self) -> None:
        """parse() filters invalid string types."""
        raw = {
            "http_server": 123,  # Invalid: int, not str
            "http_powered_by": "Strfry",  # Valid
        }
        parsed = Nip66HttpData.parse(raw)
        data = Nip66HttpData(**parsed)
        assert data.http_server is None
        assert data.http_powered_by == "Strfry"

    def test_parse_filters_blank_http_strings(self) -> None:
        """parse() filters blank or whitespace-only HTTP header strings."""
        raw = {
            "http_server": "",
            "http_powered_by": " ",
        }
        parsed = Nip66HttpData.parse(raw)
        assert parsed == {}

    def test_to_dict_excludes_none(self) -> None:
        """to_dict() excludes None values."""
        data = Nip66HttpData(http_server="nginx/1.24.0")
        d = data.to_dict()
        assert d == {"http_server": "nginx/1.24.0"}
        assert "http_powered_by" not in d
