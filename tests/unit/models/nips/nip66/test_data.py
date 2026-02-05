"""
Unit tests for models.nips.nip66.data module.

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

from models.nips.nip66.data import (
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

    def test_parse_ignores_unknown_fields(self) -> None:
        """parse() ignores fields not in spec."""
        raw = {"rtt_open": 100, "unknown_field": "ignored"}
        parsed = Nip66RttData.parse(raw)
        assert "unknown_field" not in parsed
        data = Nip66RttData(**parsed)
        assert data.rtt_open == 100

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
            ssl_version=3,
            ssl_fingerprint="SHA256:AB:CD",
            ssl_protocol="TLSv1.3",
            ssl_cipher="TLS_AES_256_GCM_SHA384",
            ssl_cipher_bits=256,
        )
        assert data.ssl_valid is True
        assert data.ssl_subject_cn == "relay.example.com"
        assert data.ssl_issuer == "Let's Encrypt"
        assert data.ssl_cipher_bits == 256

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
            "ssl_version": 3,  # Valid
            "ssl_cipher_bits": "256",  # Invalid: string, not int
        }
        parsed = Nip66SslData.parse(raw)
        data = Nip66SslData(**parsed)
        assert data.ssl_expires is None
        assert data.ssl_version == 3
        assert data.ssl_cipher_bits is None

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
        """parse() preserves valid SAN list."""
        raw = {"ssl_san": ["relay.example.com", "*.example.com"]}
        parsed = Nip66SslData.parse(raw)
        data = Nip66SslData(**parsed)
        assert data.ssl_san == ["relay.example.com", "*.example.com"]

    def test_parse_filters_empty_san_list(self) -> None:
        """parse() filters empty SAN list."""
        raw = {"ssl_san": []}
        parsed = Nip66SslData.parse(raw)
        data = Nip66SslData(**parsed)
        assert data.ssl_san is None

    def test_parse_filters_invalid_san_elements(self) -> None:
        """parse() filters invalid elements in SAN list."""
        raw = {"ssl_san": ["relay.example.com", 123, None, "*.example.com"]}
        parsed = Nip66SslData.parse(raw)
        data = Nip66SslData(**parsed)
        assert data.ssl_san == ["relay.example.com", "*.example.com"]


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
            geohash="9q9hvu7wp",
            geo_geoname_id=5375480,
        )
        assert data.geo_country == "US"
        assert data.geo_lat == 37.386
        assert data.geo_is_eu is False
        assert data.geo_geoname_id == 5375480

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
        assert data.dns_ips == ["8.8.8.8", "8.8.4.4"]
        assert data.dns_ttl == 300
        assert len(data.dns_ns) == 2

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
            "dns_ips": ["8.8.8.8", 123, None, "8.8.4.4"],
            "dns_ns": ["ns1.google.com", 456, "ns2.google.com"],
        }
        parsed = Nip66DnsData.parse(raw)
        data = Nip66DnsData(**parsed)
        assert data.dns_ips == ["8.8.8.8", "8.8.4.4"]
        assert data.dns_ns == ["ns1.google.com", "ns2.google.com"]

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

    def test_to_dict_excludes_none(self) -> None:
        """to_dict() excludes None values."""
        data = Nip66HttpData(http_server="nginx/1.24.0")
        d = data.to_dict()
        assert d == {"http_server": "nginx/1.24.0"}
        assert "http_powered_by" not in d
