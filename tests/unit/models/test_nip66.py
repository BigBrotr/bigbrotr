"""
Unit tests for models.nip66 module.

Tests:
- Nip66 construction and validation
- Metadata parsing and type validation
- to_relay_metadata() conversion (generates up to 5 records)
- Internal helper methods (_check_ssl_sync, _lookup_geo_sync, _resolve_dns_sync)
- Nip66.test() async connection tests
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models import Metadata, Nip66, Relay, RelayMetadata
from models.nip66 import Nip66TestError
from models.relay_metadata import MetadataType


@pytest.fixture
def relay():
    """Create a clearnet test relay."""
    return Relay(raw_url="wss://relay.example.com", discovered_at=1234567890)


@pytest.fixture
def tor_relay():
    """Create a Tor relay."""
    return Relay(raw_url="wss://abcdef1234567890.onion", discovered_at=1234567890)


@pytest.fixture
def ws_relay():
    """Create a ws:// relay (no SSL)."""
    return Relay(raw_url="ws://relay.example.com", discovered_at=1234567890)


@pytest.fixture
def complete_rtt_data():
    """Complete RTT metadata."""
    return {
        "rtt_open": 100,
        "rtt_read": 150,
        "rtt_write": 200,
    }


@pytest.fixture
def complete_ssl_data():
    """Complete SSL metadata."""
    return {
        "ssl_valid": True,
        "ssl_subject_cn": "relay.example.com",
        "ssl_issuer": "Let's Encrypt",
        "ssl_issuer_cn": "R3",
        "ssl_expires": 1735689600,
        "ssl_not_before": 1727827200,
        "ssl_san": ["relay.example.com", "*.example.com"],
        "ssl_serial": "04ABCDEF12345678",  # pragma: allowlist secret
        "ssl_version": 3,
        "ssl_fingerprint": "SHA256:AB:CD:EF:12:34:56",
        "ssl_protocol": "TLSv1.3",
        "ssl_cipher": "TLS_AES_256_GCM_SHA384",
        "ssl_cipher_bits": 256,
    }


@pytest.fixture
def complete_geo_data():
    """Complete geo metadata."""
    return {
        "geo_ip": "8.8.8.8",
        "geo_country": "US",
        "geo_country_name": "United States",
        "geo_continent": "NA",
        "geo_continent_name": "North America",
        "geo_is_eu": False,
        "geo_region": "California",
        "geo_city": "Mountain View",
        "geo_postal": "94035",
        "geo_lat": 37.386,
        "geo_lon": -122.084,
        "geo_accuracy": 10,
        "geo_tz": "America/Los_Angeles",
        "geohash": "9q9hvu7wp",
        "geo_geoname_id": 5375480,
        "geo_asn": 15169,
        "geo_asn_org": "GOOGLE",
        "geo_network": "8.8.8.0/24",
    }


@pytest.fixture
def complete_dns_data():
    """Complete DNS metadata."""
    return {
        "dns_ip": "8.8.8.8",
        "dns_ipv6": "2001:4860:4860::8888",
        "dns_ips": ["8.8.8.8", "8.8.4.4"],
        "dns_ips_v6": ["2001:4860:4860::8888"],
        "dns_cname": "dns.google",
        "dns_reverse": "dns.google",
        "dns_ns": ["ns1.google.com", "ns2.google.com"],
        "dns_ttl": 300,
        "dns_rtt": 50,
    }


@pytest.fixture
def complete_http_data():
    """Complete HTTP metadata."""
    return {
        "http_server": "nginx/1.24.0",
        "http_powered_by": "Strfry",
    }


@pytest.fixture
def nip66_full(
    relay,
    complete_rtt_data,
    complete_ssl_data,
    complete_geo_data,
    complete_dns_data,
    complete_http_data,
):
    """Nip66 with all metadata types."""
    return Nip66(
        relay=relay,
        rtt_metadata=complete_rtt_data,
        ssl_metadata=complete_ssl_data,
        geo_metadata=complete_geo_data,
        dns_metadata=complete_dns_data,
        http_metadata=complete_http_data,
        generated_at=1234567890,
    )


@pytest.fixture
def nip66_rtt_only(relay, complete_rtt_data):
    """Nip66 with RTT metadata only."""
    return Nip66(
        relay=relay,
        rtt_metadata=complete_rtt_data,
        generated_at=1234567890,
    )


@pytest.fixture
def mock_keys():
    """Mock Keys object for RTT tests."""
    keys = MagicMock()
    keys._inner = MagicMock()
    return keys


@pytest.fixture
def mock_nostr_client():
    """Mock nostr-sdk client with WebSocketClient transport pattern."""
    mock_client = AsyncMock()
    mock_client.add_relay = AsyncMock()
    mock_client.connect = AsyncMock()
    mock_client.wait_for_connection = AsyncMock()
    mock_client.disconnect = AsyncMock()
    mock_client.fetch_events_of = AsyncMock(return_value=[MagicMock()])

    # Mock relay() -> RelayObject with is_connected() (sync method)
    mock_relay_obj = MagicMock()
    mock_relay_obj.is_connected.return_value = True
    mock_client.relay = AsyncMock(return_value=mock_relay_obj)

    # Mock stream_events() for read test
    mock_stream = AsyncMock()
    mock_stream.next = AsyncMock(return_value=MagicMock())  # Returns an event
    mock_client.stream_events = AsyncMock(return_value=mock_stream)

    # Mock send_event_builder() for write test
    mock_output = MagicMock()
    mock_output.success = ["wss://relay.example.com"]
    mock_output.failed = []
    mock_output.id = MagicMock()
    mock_client.send_event_builder = AsyncMock(return_value=mock_output)
    return mock_client


class TestConstruction:
    """Test Nip66 construction and validation."""

    def test_with_all_metadata(
        self,
        relay,
        complete_rtt_data,
        complete_ssl_data,
        complete_geo_data,
        complete_dns_data,
        complete_http_data,
    ):
        """Construct with all five metadata types."""
        nip66 = Nip66(
            relay=relay,
            rtt_metadata=complete_rtt_data,
            ssl_metadata=complete_ssl_data,
            geo_metadata=complete_geo_data,
            dns_metadata=complete_dns_data,
            http_metadata=complete_http_data,
        )
        assert nip66.relay is relay
        assert nip66.rtt_metadata is not None
        assert nip66.ssl_metadata is not None
        assert nip66.geo_metadata is not None
        assert nip66.dns_metadata is not None
        assert nip66.http_metadata is not None

    def test_with_rtt_only(self, relay, complete_rtt_data):
        """Construct with RTT metadata only, others are None."""
        nip66 = Nip66(relay=relay, rtt_metadata=complete_rtt_data)
        # RTT has data
        assert nip66.rtt_metadata.data["rtt_open"] == 100
        # Others are None
        assert nip66.ssl_metadata is None
        assert nip66.geo_metadata is None
        assert nip66.dns_metadata is None
        assert nip66.http_metadata is None

    def test_with_ssl_only(self, relay, complete_ssl_data):
        """Construct with SSL metadata only, others are None."""
        nip66 = Nip66(relay=relay, ssl_metadata=complete_ssl_data)
        assert nip66.rtt_metadata is None
        assert nip66.ssl_metadata.data["ssl_valid"] is True
        assert nip66.geo_metadata is None

    def test_with_geo_only(self, relay, complete_geo_data):
        """Construct with geo metadata only, others are None."""
        nip66 = Nip66(relay=relay, geo_metadata=complete_geo_data)
        assert nip66.rtt_metadata is None
        assert nip66.ssl_metadata is None
        assert nip66.geo_metadata.data["geo_country"] == "US"

    def test_with_dns_only(self, relay, complete_dns_data):
        """Construct with DNS metadata only, others are None."""
        nip66 = Nip66(relay=relay, dns_metadata=complete_dns_data)
        assert nip66.dns_metadata.data["dns_ip"] == "8.8.8.8"
        assert nip66.rtt_metadata is None

    def test_with_http_only(self, relay, complete_http_data):
        """Construct with HTTP metadata only, others are None."""
        nip66 = Nip66(relay=relay, http_metadata=complete_http_data)
        assert nip66.http_metadata.data["http_server"] == "nginx/1.24.0"
        assert nip66.rtt_metadata is None

    def test_no_metadata_raises_error(self, relay):
        """Construction without any metadata raises ValueError."""
        with pytest.raises(ValueError, match="At least one"):
            Nip66(relay=relay)

    def test_empty_metadata_becomes_none(self, relay, complete_rtt_data):
        """Empty metadata dict becomes None."""
        nip66 = Nip66(
            relay=relay,
            rtt_metadata=complete_rtt_data,
            ssl_metadata={},
            geo_metadata={},
            dns_metadata={},
            http_metadata={},
        )
        # RTT has data
        assert nip66.rtt_metadata.data["rtt_open"] == 100
        # Others are None (empty {} becomes None)
        assert nip66.ssl_metadata is None
        assert nip66.geo_metadata is None
        assert nip66.dns_metadata is None
        assert nip66.http_metadata is None

    def test_generated_at_default(self, relay, complete_rtt_data):
        """generated_at defaults to current time."""
        nip66 = Nip66(relay=relay, rtt_metadata=complete_rtt_data)
        assert nip66.generated_at > 0

    def test_generated_at_explicit(self, relay, complete_rtt_data):
        """Explicit generated_at is preserved."""
        nip66 = Nip66(relay=relay, rtt_metadata=complete_rtt_data, generated_at=1000)
        assert nip66.generated_at == 1000


class TestMetadataAccess:
    """Test metadata access via .data dict."""

    def test_rtt_metadata_access(self, nip66_full):
        """Access RTT values via metadata.data."""
        assert nip66_full.rtt_metadata.data.get("rtt_open") == 100
        assert nip66_full.rtt_metadata.data.get("rtt_read") == 150
        assert nip66_full.rtt_metadata.data.get("rtt_write") == 200

    def test_ssl_metadata_access(self, nip66_full):
        """Access SSL values via metadata.data."""
        assert nip66_full.ssl_metadata.data.get("ssl_valid") is True
        assert nip66_full.ssl_metadata.data.get("ssl_issuer") == "Let's Encrypt"
        assert nip66_full.ssl_metadata.data.get("ssl_protocol") == "TLSv1.3"
        assert nip66_full.ssl_metadata.data.get("ssl_cipher_bits") == 256

    def test_geo_metadata_access(self, nip66_full):
        """Access geo values via metadata.data."""
        assert nip66_full.geo_metadata.data.get("geo_country") == "US"
        assert nip66_full.geo_metadata.data.get("geo_country_name") == "United States"
        assert nip66_full.geo_metadata.data.get("geo_is_eu") is False
        assert nip66_full.geo_metadata.data.get("geo_network") == "8.8.8.0/24"

    def test_dns_metadata_access(self, nip66_full):
        """Access DNS values via metadata.data."""
        assert nip66_full.dns_metadata.data.get("dns_ip") == "8.8.8.8"
        assert nip66_full.dns_metadata.data.get("dns_ipv6") == "2001:4860:4860::8888"
        assert nip66_full.dns_metadata.data.get("dns_ttl") == 300
        assert len(nip66_full.dns_metadata.data.get("dns_ips")) == 2

    def test_http_metadata_access(self, nip66_full):
        """Access HTTP values via metadata.data."""
        assert nip66_full.http_metadata.data.get("http_server") == "nginx/1.24.0"
        assert nip66_full.http_metadata.data.get("http_powered_by") == "Strfry"


class TestMetadataParsing:
    """Test metadata parsing and type validation."""

    def test_filters_invalid_rtt_types(self, relay):
        """Invalid types in RTT metadata are filtered."""
        data = {
            "rtt_open": "fast",  # Invalid: should be int
            "rtt_read": 150,  # Valid
        }
        nip66 = Nip66(relay=relay, rtt_metadata=data)
        assert nip66.rtt_metadata is not None
        assert nip66.rtt_metadata.data.get("rtt_open") is None
        assert nip66.rtt_metadata.data.get("rtt_read") == 150

    def test_filters_invalid_ssl_types(self, relay):
        """Invalid types in SSL metadata are filtered."""
        data = {
            "ssl_valid": "yes",  # Invalid: should be bool
            "ssl_issuer": 123,  # Invalid: should be str
            "ssl_expires": 1735689600,  # Valid
        }
        nip66 = Nip66(relay=relay, ssl_metadata=data)
        assert nip66.ssl_metadata is not None
        assert nip66.ssl_metadata.data.get("ssl_valid") is None
        assert nip66.ssl_metadata.data.get("ssl_issuer") is None
        assert nip66.ssl_metadata.data.get("ssl_expires") == 1735689600

    def test_filters_invalid_geo_types(self, relay):
        """Invalid types in geo metadata are filtered."""
        data = {
            "geo_ip": 127001,  # Invalid: should be str
            "geo_country": "US",  # Valid
            "geo_lat": "37.386",  # Invalid: should be float
            "geo_lon": -122.084,  # Valid
            "geo_asn": "15169",  # Invalid: should be int
        }
        nip66 = Nip66(relay=relay, geo_metadata=data)
        assert nip66.geo_metadata is not None
        assert nip66.geo_metadata.data.get("geo_ip") is None
        assert nip66.geo_metadata.data.get("geo_country") == "US"
        assert nip66.geo_metadata.data.get("geo_lat") is None
        assert nip66.geo_metadata.data.get("geo_lon") == -122.084
        assert nip66.geo_metadata.data.get("geo_asn") is None

    def test_filters_empty_strings(self, relay):
        """Empty strings are filtered out."""
        data = {
            "ssl_valid": True,
            "ssl_issuer": "",  # Empty string
            "ssl_subject_cn": "  ",  # Whitespace only
        }
        nip66 = Nip66(relay=relay, ssl_metadata=data)
        assert nip66.ssl_metadata is not None
        assert nip66.ssl_metadata.data.get("ssl_valid") is True
        assert nip66.ssl_metadata.data.get("ssl_issuer") is None
        assert nip66.ssl_metadata.data.get("ssl_subject_cn") is None

    def test_filters_empty_lists(self, relay):
        """Empty lists are filtered out."""
        data = {
            "dns_ip": "8.8.8.8",
            "dns_ips": [],  # Empty list
            "dns_ns": ["ns1.google.com"],  # Non-empty list
        }
        nip66 = Nip66(relay=relay, dns_metadata=data)
        assert nip66.dns_metadata is not None
        assert nip66.dns_metadata.data.get("dns_ip") == "8.8.8.8"
        assert nip66.dns_metadata.data.get("dns_ips") is None
        assert nip66.dns_metadata.data.get("dns_ns") == ["ns1.google.com"]

    def test_filters_invalid_list_elements(self, relay):
        """Invalid types inside lists are filtered out."""
        data = {
            "dns_ip": "8.8.8.8",
            "dns_ips": ["8.8.8.8", 123, "8.8.4.4"],  # Int mixed in
            "dns_ns": ["ns1.google.com", None, "ns2.google.com"],  # None mixed in
        }
        nip66 = Nip66(relay=relay, dns_metadata=data)
        assert nip66.dns_metadata is not None
        assert nip66.dns_metadata.data.get("dns_ips") == ["8.8.8.8", "8.8.4.4"]
        assert nip66.dns_metadata.data.get("dns_ns") == ["ns1.google.com", "ns2.google.com"]

    def test_list_with_only_invalid_elements_becomes_none(self, relay):
        """List with only invalid elements becomes None."""
        data = {
            "dns_ip": "8.8.8.8",
            "dns_ips": [123, 456, 789],  # All invalid
            "dns_ns": [None, None],  # All None
        }
        nip66 = Nip66(relay=relay, dns_metadata=data)
        assert nip66.dns_metadata is not None
        assert nip66.dns_metadata.data.get("dns_ips") is None
        assert nip66.dns_metadata.data.get("dns_ns") is None

    def test_filters_empty_strings_in_lists(self, relay):
        """Empty strings inside lists are filtered out."""
        dns_data = {
            "dns_ip": "8.8.8.8",
            "dns_ips": ["8.8.8.8", "", "8.8.4.4", "   "],  # Empty/whitespace strings
        }
        nip66 = Nip66(relay=relay, dns_metadata=dns_data)
        assert nip66.dns_metadata.data.get("dns_ips") == ["8.8.8.8", "8.8.4.4"]

        ssl_data = {
            "ssl_valid": True,
            "ssl_san": ["relay.example.com", "", "*.example.com"],
        }
        nip66_ssl = Nip66(relay=relay, ssl_metadata=ssl_data)
        assert nip66_ssl.ssl_metadata.data.get("ssl_san") == ["relay.example.com", "*.example.com"]


class TestToRelayMetadata:
    """Test to_relay_metadata() method."""

    def test_returns_tuple_of_five(self, nip66_full):
        """Returns tuple of five RelayMetadata objects."""
        rtt, ssl, geo, dns, http = nip66_full.to_relay_metadata()
        assert isinstance(rtt, RelayMetadata)
        assert isinstance(ssl, RelayMetadata)
        assert isinstance(geo, RelayMetadata)
        assert isinstance(dns, RelayMetadata)
        assert isinstance(http, RelayMetadata)

    def test_correct_metadata_types(self, nip66_full):
        """Each RelayMetadata has correct type."""
        rtt, ssl, geo, dns, http = nip66_full.to_relay_metadata()
        assert rtt.metadata_type == MetadataType.NIP66_RTT
        assert ssl.metadata_type == MetadataType.NIP66_SSL
        assert geo.metadata_type == MetadataType.NIP66_GEO
        assert dns.metadata_type == MetadataType.NIP66_DNS
        assert http.metadata_type == MetadataType.NIP66_HTTP

    def test_returns_none_for_missing_metadata(self, nip66_rtt_only):
        """Returns None for missing metadata types."""
        rtt, ssl, geo, dns, http = nip66_rtt_only.to_relay_metadata()
        # RTT has data
        assert isinstance(rtt, RelayMetadata)
        assert rtt.metadata.data["rtt_open"] == 100
        # Others are None
        assert ssl is None
        assert geo is None
        assert dns is None
        assert http is None

    def test_preserves_relay(self, nip66_full):
        """Each RelayMetadata preserves relay reference."""
        rtt, ssl, geo, dns, http = nip66_full.to_relay_metadata()
        assert rtt.relay is nip66_full.relay
        assert ssl.relay is nip66_full.relay
        assert geo.relay is nip66_full.relay
        assert dns.relay is nip66_full.relay
        assert http.relay is nip66_full.relay

    def test_preserves_generated_at(self, nip66_full):
        """Each RelayMetadata preserves generated_at timestamp."""
        rtt, ssl, geo, dns, http = nip66_full.to_relay_metadata()
        assert rtt.generated_at == 1234567890
        assert ssl.generated_at == 1234567890
        assert geo.generated_at == 1234567890
        assert dns.generated_at == 1234567890
        assert http.generated_at == 1234567890


class TestCheckSslSync:
    """Test _check_ssl_sync() static method."""

    def test_success_returns_valid_cert(self):
        """Successful SSL check returns ssl_valid=True and cert info."""
        mock_cert = {
            "subject": ((("commonName", "relay.example.com"),),),
            "issuer": (
                (("organizationName", "Test CA"),),
                (("commonName", "Test CA Root"),),
            ),
            "notAfter": "Jan  1 00:00:00 2025 GMT",
            "notBefore": "Jan  1 00:00:00 2024 GMT",
            "subjectAltName": (("DNS", "relay.example.com"), ("DNS", "*.example.com")),
            "serialNumber": "ABCD1234",
            "version": 3,
        }
        mock_cert_binary = b"binary cert data"

        with patch("socket.create_connection") as mock_conn:
            mock_socket = MagicMock()
            mock_conn.return_value.__enter__.return_value = mock_socket
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)

            with patch("ssl.create_default_context") as mock_ctx:
                mock_ssl_socket = MagicMock()
                mock_ssl_socket.getpeercert.side_effect = [mock_cert, mock_cert_binary]
                mock_ssl_socket.version.return_value = "TLSv1.3"
                mock_ssl_socket.cipher.return_value = ("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256)
                mock_wrapped = MagicMock()
                mock_wrapped.__enter__.return_value = mock_ssl_socket
                mock_wrapped.__exit__ = MagicMock(return_value=False)
                mock_ctx.return_value.wrap_socket.return_value = mock_wrapped

                result = Nip66._check_ssl_sync("example.com", 443, 30.0)

        assert result["ssl_valid"] is True
        assert result.get("ssl_subject_cn") == "relay.example.com"
        assert result.get("ssl_issuer") == "Test CA"
        assert result.get("ssl_issuer_cn") == "Test CA Root"
        assert "ssl_expires" in result
        assert "ssl_not_before" in result
        assert result.get("ssl_san") == ["relay.example.com", "*.example.com"]
        assert result.get("ssl_serial") == "ABCD1234"
        assert result.get("ssl_version") == 3
        assert result.get("ssl_protocol") == "TLSv1.3"
        assert result.get("ssl_cipher") == "TLS_AES_256_GCM_SHA384"
        assert result.get("ssl_cipher_bits") == 256

    def test_ssl_error_returns_dict_with_ssl_valid_false(self):
        """SSL error is handled internally and returns dict with ssl_valid=False."""
        import ssl as ssl_module

        with patch("socket.create_connection") as mock_conn:
            mock_socket = MagicMock()
            mock_conn.return_value.__enter__.return_value = mock_socket
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)

            with patch("ssl.create_default_context") as mock_ctx:
                mock_ctx.return_value.wrap_socket.side_effect = ssl_module.SSLError()
                result = Nip66._check_ssl_sync("example.com", 443, 30.0)

        # SSL error is caught, returns dict with ssl_valid=False
        assert result.get("ssl_valid") is False

    def test_connection_error_returns_dict_with_ssl_valid_false(self):
        """Connection error is handled internally and returns dict with ssl_valid=False."""
        with patch("socket.create_connection", side_effect=TimeoutError()):
            result = Nip66._check_ssl_sync("example.com", 443, 30.0)

        # Connection error is caught, returns dict with ssl_valid=False
        assert result.get("ssl_valid") is False


class TestLookupGeoSync:
    """Test _lookup_geo_sync() static method."""

    def test_success_with_city_reader(self):
        """Successful lookup returns geo data."""
        mock_response = MagicMock()
        mock_response.country.iso_code = "US"
        mock_response.country.name = "United States"
        mock_response.country.is_in_european_union = False
        mock_response.registered_country.iso_code = None
        mock_response.registered_country.name = None
        mock_response.continent.code = "NA"
        mock_response.continent.name = "North America"
        mock_response.city.name = "Mountain View"
        mock_response.city.geoname_id = 5375480
        mock_response.postal.code = "94035"
        mock_response.location.latitude = 37.386
        mock_response.location.longitude = -122.084
        mock_response.location.accuracy_radius = 10
        mock_response.location.time_zone = "America/Los_Angeles"
        mock_response.subdivisions.most_specific.name = "California"

        mock_city_reader = MagicMock()
        mock_city_reader.city.return_value = mock_response

        result = Nip66._lookup_geo_sync("8.8.8.8", mock_city_reader, None)

        assert result["geo_ip"] == "8.8.8.8"
        assert result["geo_country"] == "US"
        assert result["geo_country_name"] == "United States"
        assert result["geo_is_eu"] is False
        assert result["geo_continent"] == "NA"
        assert result["geo_continent_name"] == "North America"
        assert result["geo_city"] == "Mountain View"
        assert result["geo_geoname_id"] == 5375480
        assert result["geo_postal"] == "94035"
        assert result["geo_lat"] == 37.386
        assert result["geo_lon"] == -122.084
        assert result["geo_accuracy"] == 10
        assert result["geo_tz"] == "America/Los_Angeles"
        assert result["geo_region"] == "California"
        assert "geohash" in result

    def test_success_with_asn_reader(self):
        """Lookup with ASN reader includes ASN data."""
        mock_city_response = MagicMock()
        mock_city_response.country.iso_code = "US"
        mock_city_response.country.name = None
        mock_city_response.country.is_in_european_union = None
        mock_city_response.registered_country.iso_code = None
        mock_city_response.registered_country.name = None
        mock_city_response.continent.code = None
        mock_city_response.continent.name = None
        mock_city_response.city.name = None
        mock_city_response.city.geoname_id = None
        mock_city_response.postal.code = None
        mock_city_response.location.latitude = 37.0
        mock_city_response.location.longitude = -122.0
        mock_city_response.location.accuracy_radius = None
        mock_city_response.location.time_zone = None
        mock_city_response.subdivisions = []

        mock_asn_response = MagicMock()
        mock_asn_response.autonomous_system_number = 7922
        mock_asn_response.autonomous_system_organization = "Comcast Cable"
        mock_asn_response.network = "1.2.3.0/24"

        mock_city_reader = MagicMock()
        mock_city_reader.city.return_value = mock_city_response

        mock_asn_reader = MagicMock()
        mock_asn_reader.asn.return_value = mock_asn_response

        result = Nip66._lookup_geo_sync("8.8.8.8", mock_city_reader, mock_asn_reader)

        assert result["geo_asn"] == 7922
        assert result["geo_asn_org"] == "Comcast Cable"
        assert result["geo_network"] == "1.2.3.0/24"


class TestResolveDnsSync:
    """Test _resolve_dns_sync() static method."""

    def test_success_returns_dns_data(self):
        """Successful DNS resolution returns comprehensive data."""
        mock_a_response = MagicMock()
        mock_a_response.__iter__ = lambda _: iter([MagicMock(address="8.8.8.8")])
        mock_a_response.rrset.ttl = 300

        mock_resolver = MagicMock()
        mock_resolver.resolve.return_value = mock_a_response

        with patch("dns.resolver.Resolver", return_value=mock_resolver):
            result = Nip66._resolve_dns_sync("example.com", 5.0)

        assert result.get("dns_ip") == "8.8.8.8"
        assert "dns_rtt" in result


class TestTestSsl:
    """Test _test_ssl() class method."""

    @pytest.mark.asyncio
    async def test_clearnet_wss_returns_ssl_data(self, relay):
        """Returns SSL data for clearnet wss:// relay."""
        ssl_result = {
            "ssl_valid": True,
            "ssl_issuer": "Test CA",
            "ssl_protocol": "TLSv1.3",
        }

        with patch.object(Nip66, "_check_ssl_sync", return_value=ssl_result):
            result = await Nip66._test_ssl(relay, 10.0)

        assert isinstance(result, Metadata)
        assert result.data.get("ssl_valid") is True
        assert result.data.get("ssl_protocol") == "TLSv1.3"

    @pytest.mark.asyncio
    async def test_ssl_failure_raises_error(self, relay):
        """Raises Nip66TestError when SSL check fails."""
        # Mock _check_ssl_sync to return empty dict (SSL check failed)
        with (
            patch.object(Nip66, "_check_ssl_sync", return_value={}),
            pytest.raises(Nip66TestError) as exc_info,
        ):
            await Nip66._test_ssl(relay, 10.0)
        assert "returned no data" in str(exc_info.value.cause)

    @pytest.mark.asyncio
    async def test_tor_raises_error(self, tor_relay):
        """Raises Nip66TestError for Tor relay."""
        with pytest.raises(Nip66TestError) as exc_info:
            await Nip66._test_ssl(tor_relay, 10.0)
        assert "not applicable" in str(exc_info.value.cause)


class TestTestGeo:
    """Test _test_geo() class method."""

    @pytest.mark.asyncio
    async def test_clearnet_with_reader_returns_geo_data(self, relay):
        """Returns geo data for clearnet relay with city reader."""
        geo_result = {
            "geo_ip": "8.8.8.8",
            "geo_country": "US",
            "geo_country_name": "United States",
        }

        mock_city_reader = MagicMock()
        mock_asn_reader = MagicMock()

        with (
            patch("socket.gethostbyname", return_value="8.8.8.8"),
            patch.object(Nip66, "_lookup_geo_sync", return_value=geo_result),
        ):
            result = await Nip66._test_geo(relay, mock_city_reader, mock_asn_reader)

        assert isinstance(result, Metadata)
        assert result.data.get("geo_country") == "US"

    @pytest.mark.asyncio
    async def test_tor_raises_error(self, tor_relay):
        """Raises Nip66TestError for Tor relay."""
        mock_city_reader = MagicMock()
        mock_asn_reader = MagicMock()
        with pytest.raises(Nip66TestError) as exc_info:
            await Nip66._test_geo(tor_relay, mock_city_reader, mock_asn_reader)
        assert "not applicable" in str(exc_info.value.cause)


class TestTestDns:
    """Test _test_dns() class method."""

    @pytest.mark.asyncio
    async def test_clearnet_returns_dns_data(self, relay):
        """Returns DNS data for clearnet relay."""
        dns_result = {
            "dns_ip": "8.8.8.8",
            "dns_ips": ["8.8.8.8"],
            "dns_ttl": 300,
            "dns_rtt": 50,
        }

        with patch.object(Nip66, "_resolve_dns_sync", return_value=dns_result):
            result = await Nip66._test_dns(relay, 5.0)

        assert isinstance(result, Metadata)
        assert result.data.get("dns_ip") == "8.8.8.8"
        assert result.data.get("dns_rtt") == 50

    @pytest.mark.asyncio
    async def test_tor_raises_error(self, tor_relay):
        """Raises Nip66TestError for Tor relay."""
        with pytest.raises(Nip66TestError) as exc_info:
            await Nip66._test_dns(tor_relay, 5.0)
        assert "not applicable" in str(exc_info.value.cause)


class TestTestHttp:
    """Test _test_http() class method."""

    @pytest.mark.asyncio
    async def test_clearnet_returns_http_data(self, relay):
        """Returns HTTP data for clearnet relay."""
        http_result = {
            "http_server": "nginx/1.24.0",
            "http_powered_by": "Strfry",
        }

        async def mock_check_http(*args, **kwargs):
            return http_result

        with patch.object(Nip66, "_check_http", mock_check_http):
            result = await Nip66._test_http(relay, 10.0)

        assert isinstance(result, Metadata)
        assert result.data.get("http_server") == "nginx/1.24.0"

    @pytest.mark.asyncio
    async def test_tor_without_proxy_raises_error(self, tor_relay):
        """Raises Nip66TestError for Tor relay without proxy."""
        with pytest.raises(Nip66TestError) as exc_info:
            await Nip66._test_http(tor_relay, 10.0)
        assert "requires proxy url" in str(exc_info.value.cause)


class TestTestRtt:
    """Test _test_rtt() class method with create_client factory."""

    @pytest.mark.asyncio
    async def test_clearnet_returns_rtt_data(self, relay, mock_keys, mock_nostr_client):
        """Returns RTT data for clearnet relay using create_client factory."""
        mock_event_builder = MagicMock()
        mock_read_filter = MagicMock()

        # Mock create_client to return our mock client
        async def mock_create_client(r, k, proxy=None):
            return mock_nostr_client

        with patch("core.transport.create_client", side_effect=mock_create_client):
            result = await Nip66._test_rtt(
                relay,
                timeout=10.0,
                keys=mock_keys,
                event_builder=mock_event_builder,
                read_filter=mock_read_filter,
            )

        assert isinstance(result, Metadata)
        assert result.data.get("rtt_open") is not None

    @pytest.mark.asyncio
    async def test_tor_without_proxy_raises_error(self, tor_relay, mock_keys):
        """Raises Nip66TestError for Tor relay without proxy."""
        mock_event_builder = MagicMock()
        mock_read_filter = MagicMock()

        # create_client raises ValueError for overlay network without proxy
        async def mock_create_client(r, k, proxy=None):
            if r.network in ("tor", "i2p", "loki") and proxy is None:
                raise ValueError(f"Overlay network relay ({r.network}) requires proxy_url")
            return MagicMock()

        with (
            patch("core.transport.create_client", side_effect=mock_create_client),
            pytest.raises(Nip66TestError) as exc_info,
        ):
            await Nip66._test_rtt(
                tor_relay,
                timeout=10.0,
                keys=mock_keys,
                event_builder=mock_event_builder,
                read_filter=mock_read_filter,
            )
        assert "requires proxy_url" in str(exc_info.value.cause)

    @pytest.mark.asyncio
    async def test_connection_failure_raises_error(self, relay, mock_keys):
        """Raises Nip66TestError when connection fails."""
        mock_event_builder = MagicMock()
        mock_read_filter = MagicMock()

        mock_client = AsyncMock()
        mock_client.connect = AsyncMock(side_effect=Exception("Connection refused"))

        async def mock_create_client(r, k, proxy=None):
            return mock_client

        with (
            patch("core.transport.create_client", side_effect=mock_create_client),
            pytest.raises(Nip66TestError) as exc_info,
        ):
            await Nip66._test_rtt(
                relay,
                timeout=10.0,
                keys=mock_keys,
                event_builder=mock_event_builder,
                read_filter=mock_read_filter,
            )
        assert "returned no data" in str(exc_info.value.cause)


class TestTest:
    """Test test() class method."""

    @pytest.mark.asyncio
    async def test_returns_nip66_on_success(self, relay, mock_keys, mock_nostr_client):
        """Returns Nip66 instance on successful test."""
        rtt_data = {"rtt_open": 100, "rtt_read": 150}
        dns_data = {"dns_ip": "8.8.8.8", "dns_rtt": 50}

        mock_event_builder = MagicMock()
        mock_read_filter = MagicMock()

        # _test_* methods now raise Nip66TestError on failure, so we mock success cases
        with (
            patch.object(
                Nip66, "_test_dns", new_callable=AsyncMock, return_value=Metadata(dns_data)
            ),
            patch.object(
                Nip66, "_test_rtt", new_callable=AsyncMock, return_value=Metadata(rtt_data)
            ),
            # SSL, geo, http raise Nip66TestError (simulating failure)
            patch.object(
                Nip66,
                "_test_ssl",
                new_callable=AsyncMock,
                side_effect=Nip66TestError(relay, ValueError("test")),
            ),
            patch.object(
                Nip66,
                "_test_geo",
                new_callable=AsyncMock,
                side_effect=Nip66TestError(relay, ValueError("test")),
            ),
            patch.object(
                Nip66,
                "_test_http",
                new_callable=AsyncMock,
                side_effect=Nip66TestError(relay, ValueError("test")),
            ),
        ):
            result = await Nip66.test(
                relay,
                keys=mock_keys,
                event_builder=mock_event_builder,
                read_filter=mock_read_filter,
            )

        assert isinstance(result, Nip66)
        assert result.rtt_metadata.data.get("rtt_open") == 100
        assert result.dns_metadata.data.get("dns_ip") == "8.8.8.8"

    @pytest.mark.asyncio
    async def test_all_tests_fail_raises_error(self, relay, mock_keys):
        """All tests failing raises Nip66TestError."""
        mock_event_builder = MagicMock()
        mock_read_filter = MagicMock()

        # All _test_* methods raise Nip66TestError
        test_error = Nip66TestError(relay, ValueError("test failed"))
        with (
            patch.object(Nip66, "_test_dns", new_callable=AsyncMock, side_effect=test_error),
            patch.object(Nip66, "_test_rtt", new_callable=AsyncMock, side_effect=test_error),
            patch.object(Nip66, "_test_ssl", new_callable=AsyncMock, side_effect=test_error),
            patch.object(Nip66, "_test_geo", new_callable=AsyncMock, side_effect=test_error),
            patch.object(Nip66, "_test_http", new_callable=AsyncMock, side_effect=test_error),
            pytest.raises(Nip66TestError),
        ):
            await Nip66.test(
                relay,
                keys=mock_keys,
                event_builder=mock_event_builder,
                read_filter=mock_read_filter,
            )

    @pytest.mark.asyncio
    async def test_run_rtt_requires_keys_event_builder_and_read_filter(self, relay):
        """run_rtt=True without keys/event_builder/read_filter raises Nip66TestError."""
        # Disable all other tests so only RTT is attempted
        # _test_rtt raises Nip66TestError for missing params, which then causes
        # test() to raise Nip66TestError because no metadata was collected
        with pytest.raises(Nip66TestError):
            await Nip66.test(
                relay,
                run_rtt=True,
                run_ssl=False,
                run_geo=False,
                run_dns=False,
                run_http=False,
                keys=None,
                event_builder=None,
                read_filter=None,
            )

    @pytest.mark.asyncio
    async def test_can_skip_all_except_dns(self, relay):
        """Can skip all tests except DNS - skipped tests are None."""
        dns_data = {"dns_ip": "8.8.8.8", "dns_rtt": 50}

        with patch.object(
            Nip66, "_test_dns", new_callable=AsyncMock, return_value=Metadata(dns_data)
        ):
            result = await Nip66.test(
                relay, run_rtt=False, run_ssl=False, run_geo=False, run_http=False
            )

        assert isinstance(result, Nip66)
        # DNS has data
        assert result.dns_metadata.data.get("dns_ip") == "8.8.8.8"
        assert result.dns_metadata.data.get("dns_rtt") == 50
        # Others are None
        assert result.rtt_metadata is None
        assert result.ssl_metadata is None
        assert result.geo_metadata is None
        assert result.http_metadata is None


class TestNip66TestError:
    """Test Nip66TestError exception."""

    def test_error_message(self, relay):
        """Error message contains relay URL and cause."""
        cause = ValueError("Test error")
        error = Nip66TestError(relay, cause)
        assert "relay.example.com" in str(error)
        assert "Test error" in str(error)

    def test_error_attributes(self, relay):
        """Error has relay and cause attributes."""
        cause = ValueError("Test error")
        error = Nip66TestError(relay, cause)
        assert error.relay is relay
        assert error.cause is cause
