"""
Unit tests for models.nip66 module.

Tests:
- Nip66 construction and validation
- Metadata parsing and type validation via Pydantic models
- to_relay_metadata_tuple() conversion (generates up to 6 records)
- Internal helper methods (*Metadata._*())
- Nip66.create() async connection tests
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models import Relay, RelayMetadata
from models.nips.nip66 import (
    Nip66,
    Nip66DnsData,
    Nip66DnsLogs,
    Nip66DnsMetadata,
    Nip66GeoData,
    Nip66GeoLogs,
    Nip66GeoMetadata,
    Nip66HttpData,
    Nip66HttpLogs,
    Nip66HttpMetadata,
    Nip66NetData,
    Nip66NetLogs,
    Nip66NetMetadata,
    Nip66RttData,
    Nip66RttLogs,
    Nip66RttMetadata,
    Nip66SslData,
    Nip66SslLogs,
    Nip66SslMetadata,
    RelayNip66MetadataTuple,
)
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
def complete_rtt_metadata():
    """Complete RTT metadata as Pydantic model."""
    return Nip66RttMetadata(
        data=Nip66RttData(rtt_open=100, rtt_read=150, rtt_write=200),
        logs=Nip66RttLogs(
            open_success=True,
            open_reason=None,
            read_success=True,
            read_reason=None,
            write_success=False,
            write_reason="auth-required: please authenticate",
        ),
    )


@pytest.fixture
def complete_ssl_metadata():
    """Complete SSL metadata as Pydantic model."""
    return Nip66SslMetadata(
        data=Nip66SslData(
            ssl_valid=True,
            ssl_subject_cn="relay.example.com",
            ssl_issuer="Let's Encrypt",
            ssl_issuer_cn="R3",
            ssl_expires=1735689600,
            ssl_not_before=1727827200,
            ssl_san=["relay.example.com", "*.example.com"],
            ssl_serial="04ABCDEF12345678",  # pragma: allowlist secret
            ssl_version=3,
            ssl_fingerprint="SHA256:AB:CD:EF:12:34:56",
            ssl_protocol="TLSv1.3",
            ssl_cipher="TLS_AES_256_GCM_SHA384",
            ssl_cipher_bits=256,
        ),
        logs=Nip66SslLogs(success=True, reason=None),
    )


@pytest.fixture
def complete_geo_metadata():
    """Complete geo metadata as Pydantic model."""
    return Nip66GeoMetadata(
        data=Nip66GeoData(
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
        ),
        logs=Nip66GeoLogs(success=True, reason=None),
    )


@pytest.fixture
def complete_net_metadata():
    """Complete net metadata as Pydantic model."""
    return Nip66NetMetadata(
        data=Nip66NetData(
            net_ip="8.8.8.8",
            net_ipv6="2001:4860:4860::8888",
            net_asn=15169,
            net_asn_org="GOOGLE",
            net_network="8.8.8.0/24",
            net_network_v6="2001:4860::/32",
        ),
        logs=Nip66NetLogs(success=True, reason=None),
    )


@pytest.fixture
def complete_dns_metadata():
    """Complete DNS metadata as Pydantic model."""
    return Nip66DnsMetadata(
        data=Nip66DnsData(
            dns_ips=["8.8.8.8", "8.8.4.4"],
            dns_ips_v6=["2001:4860:4860::8888"],
            dns_cname="dns.google",
            dns_reverse="dns.google",
            dns_ns=["ns1.google.com", "ns2.google.com"],
            dns_ttl=300,
        ),
        logs=Nip66DnsLogs(success=True, reason=None),
    )


@pytest.fixture
def complete_http_metadata():
    """Complete HTTP metadata as Pydantic model."""
    return Nip66HttpMetadata(
        data=Nip66HttpData(
            http_server="nginx/1.24.0",
            http_powered_by="Strfry",
        ),
        logs=Nip66HttpLogs(success=True, reason=None),
    )


@pytest.fixture
def nip66_full(
    relay,
    complete_rtt_metadata,
    complete_ssl_metadata,
    complete_geo_metadata,
    complete_net_metadata,
    complete_dns_metadata,
    complete_http_metadata,
):
    """Nip66 instance with all six metadata types populated."""
    return Nip66(
        relay=relay,
        rtt_metadata=complete_rtt_metadata,
        ssl_metadata=complete_ssl_metadata,
        geo_metadata=complete_geo_metadata,
        net_metadata=complete_net_metadata,
        dns_metadata=complete_dns_metadata,
        http_metadata=complete_http_metadata,
        generated_at=1234567890,
    )


@pytest.fixture
def nip66_rtt_only(relay, complete_rtt_metadata):
    """Nip66 instance with only RTT metadata."""
    return Nip66(
        relay=relay,
        rtt_metadata=complete_rtt_metadata,
        generated_at=1234567890,
    )


@pytest.fixture
def mock_keys():
    """Mock nostr_sdk.Keys object for RTT tests."""
    keys = MagicMock()
    keys._inner = MagicMock()
    return keys


@pytest.fixture
def mock_nostr_client():
    """Mock nostr-sdk Client for RTT connection tests."""
    mock_client = MagicMock()
    mock_client.add_relay = AsyncMock()
    mock_client.connect = AsyncMock()
    mock_client.wait_for_connection = AsyncMock()
    mock_client.disconnect = AsyncMock()
    mock_client.fetch_events_of = AsyncMock(return_value=[MagicMock()])

    mock_relay_obj = MagicMock()
    mock_relay_obj.is_connected.return_value = True
    mock_client.relay = AsyncMock(return_value=mock_relay_obj)

    mock_stream = AsyncMock()
    mock_stream.next = AsyncMock(return_value=MagicMock())
    mock_client.stream_events = AsyncMock(return_value=mock_stream)

    mock_output = MagicMock()
    mock_output.success = ["wss://relay.example.com"]
    mock_output.failed = []
    mock_output.id = MagicMock()
    mock_client.send_event_builder = AsyncMock(return_value=mock_output)
    return mock_client


class TestNip66RttLogsValidation:
    """Test Nip66RttLogs semantic validation rules."""

    def test_all_success(self):
        """All operations successful is valid."""
        logs = Nip66RttLogs(
            open_success=True,
            read_success=True,
            write_success=True,
        )
        assert logs.open_success is True
        assert logs.read_success is True
        assert logs.write_success is True

    def test_open_success_read_write_optional(self):
        """Open success with optional read/write is valid."""
        logs = Nip66RttLogs(open_success=True)
        assert logs.open_success is True
        assert logs.read_success is None
        assert logs.write_success is None

    def test_open_fail_cascades(self):
        """Open failure with cascading read/write failures is valid."""
        logs = Nip66RttLogs(
            open_success=False,
            open_reason="connection refused",
            read_success=False,
            read_reason="connection refused",
            write_success=False,
            write_reason="connection refused",
        )
        assert logs.open_success is False
        assert logs.read_success is False
        assert logs.write_success is False

    def test_partial_success_read_fail(self):
        """Open success, read failure, write untested is valid."""
        logs = Nip66RttLogs(
            open_success=True,
            read_success=False,
            read_reason="no events returned",
        )
        assert logs.open_success is True
        assert logs.read_success is False
        assert logs.write_success is None

    def test_partial_success_write_fail(self):
        """Open+read success, write failure is valid."""
        logs = Nip66RttLogs(
            open_success=True,
            read_success=True,
            write_success=False,
            write_reason="auth-required",
        )
        assert logs.open_success is True
        assert logs.read_success is True
        assert logs.write_success is False

    def test_open_success_with_reason_raises(self):
        """Open success with reason is invalid."""
        with pytest.raises(ValueError, match="open_reason must be None when open_success is True"):
            Nip66RttLogs(
                open_success=True,
                open_reason="should not be here",
            )

    def test_open_failure_without_reason_raises(self):
        """Open failure without reason is invalid."""
        with pytest.raises(ValueError, match="open_reason is required when open_success is False"):
            Nip66RttLogs(
                open_success=False,
                open_reason=None,
            )

    def test_read_success_with_reason_raises(self):
        """Read success with reason is invalid."""
        with pytest.raises(ValueError, match="read_reason must be None when read_success is True"):
            Nip66RttLogs(
                open_success=True,
                read_success=True,
                read_reason="should not be here",
            )

    def test_read_failure_without_reason_raises(self):
        """Read failure without reason is invalid."""
        with pytest.raises(ValueError, match="read_reason is required when read_success is False"):
            Nip66RttLogs(
                open_success=True,
                read_success=False,
                read_reason=None,
            )

    def test_write_success_with_reason_raises(self):
        """Write success with reason is invalid."""
        with pytest.raises(
            ValueError, match="write_reason must be None when write_success is True"
        ):
            Nip66RttLogs(
                open_success=True,
                write_success=True,
                write_reason="should not be here",
            )

    def test_write_failure_without_reason_raises(self):
        """Write failure without reason is invalid."""
        with pytest.raises(
            ValueError, match="write_reason is required when write_success is False"
        ):
            Nip66RttLogs(
                open_success=True,
                write_success=False,
                write_reason=None,
            )

    def test_open_fail_read_success_raises(self):
        """Open failure with read success is invalid (cascade constraint)."""
        with pytest.raises(
            ValueError, match="read_success must be False when open_success is False"
        ):
            Nip66RttLogs(
                open_success=False,
                open_reason="connection refused",
                read_success=True,
            )

    def test_open_fail_write_success_raises(self):
        """Open failure with write success is invalid (cascade constraint)."""
        with pytest.raises(
            ValueError, match="write_success must be False when open_success is False"
        ):
            Nip66RttLogs(
                open_success=False,
                open_reason="connection refused",
                write_success=True,
            )

    def test_to_dict_excludes_none(self):
        """to_dict excludes None values."""
        logs = Nip66RttLogs(open_success=True)
        d = logs.to_dict()
        assert d == {"open_success": True}

    def test_to_dict_includes_all_set_values(self):
        """to_dict includes all explicitly set values."""
        logs = Nip66RttLogs(
            open_success=True,
            read_success=False,
            read_reason="timeout",
        )
        d = logs.to_dict()
        assert d == {
            "open_success": True,
            "read_success": False,
            "read_reason": "timeout",
        }


class TestConstruction:
    """Test Nip66 construction and validation."""

    def test_with_all_metadata(
        self,
        relay,
        complete_rtt_metadata,
        complete_ssl_metadata,
        complete_geo_metadata,
        complete_net_metadata,
        complete_dns_metadata,
        complete_http_metadata,
    ):
        """Construct with all six metadata types."""
        nip66 = Nip66(
            relay=relay,
            rtt_metadata=complete_rtt_metadata,
            ssl_metadata=complete_ssl_metadata,
            geo_metadata=complete_geo_metadata,
            net_metadata=complete_net_metadata,
            dns_metadata=complete_dns_metadata,
            http_metadata=complete_http_metadata,
        )
        assert nip66.relay is relay
        assert nip66.rtt_metadata is not None
        assert nip66.ssl_metadata is not None
        assert nip66.geo_metadata is not None
        assert nip66.net_metadata is not None
        assert nip66.dns_metadata is not None
        assert nip66.http_metadata is not None

    def test_with_rtt_only(self, relay, complete_rtt_metadata):
        """Construct with RTT metadata only, others are None."""
        nip66 = Nip66(relay=relay, rtt_metadata=complete_rtt_metadata)
        # RTT has data via attribute access
        assert nip66.rtt_metadata.data.rtt_open == 100
        # Probe info is in logs
        assert nip66.rtt_metadata.logs.open_success is True
        # Others are None
        assert nip66.ssl_metadata is None
        assert nip66.geo_metadata is None
        assert nip66.net_metadata is None
        assert nip66.dns_metadata is None
        assert nip66.http_metadata is None

    def test_with_ssl_only(self, relay, complete_ssl_metadata):
        """Construct with SSL metadata only, RTT is None."""
        nip66 = Nip66(relay=relay, ssl_metadata=complete_ssl_metadata)
        assert nip66.rtt_metadata is None
        assert nip66.ssl_metadata.data.ssl_valid is True
        assert nip66.geo_metadata is None

    def test_with_geo_only(self, relay, complete_geo_metadata):
        """Construct with geo metadata only."""
        nip66 = Nip66(relay=relay, geo_metadata=complete_geo_metadata)
        assert nip66.rtt_metadata is None
        assert nip66.ssl_metadata is None
        assert nip66.geo_metadata.data.geo_country == "US"

    def test_with_net_only(self, relay, complete_net_metadata):
        """Construct with net metadata only."""
        nip66 = Nip66(relay=relay, net_metadata=complete_net_metadata)
        assert nip66.net_metadata.data.net_ip == "8.8.8.8"
        assert nip66.net_metadata.data.net_asn == 15169
        assert nip66.rtt_metadata is None
        assert nip66.geo_metadata is None

    def test_with_dns_only(self, relay, complete_dns_metadata):
        """Construct with DNS metadata only."""
        nip66 = Nip66(relay=relay, dns_metadata=complete_dns_metadata)
        assert nip66.dns_metadata.data.dns_ips == ["8.8.8.8", "8.8.4.4"]
        assert nip66.rtt_metadata is None

    def test_with_http_only(self, relay, complete_http_metadata):
        """Construct with HTTP metadata only."""
        nip66 = Nip66(relay=relay, http_metadata=complete_http_metadata)
        assert nip66.http_metadata.data.http_server == "nginx/1.24.0"
        assert nip66.rtt_metadata is None

    def test_generated_at_default(self, relay, complete_rtt_metadata):
        """generated_at defaults to current time."""
        nip66 = Nip66(relay=relay, rtt_metadata=complete_rtt_metadata)
        assert nip66.generated_at > 0

    def test_generated_at_explicit(self, relay, complete_rtt_metadata):
        """Explicit generated_at is preserved."""
        nip66 = Nip66(relay=relay, rtt_metadata=complete_rtt_metadata, generated_at=1000)
        assert nip66.generated_at == 1000


class TestMetadataAccess:
    """Test metadata access via attributes."""

    def test_rtt_data_access(self, nip66_full):
        """Access RTT values via data attributes."""
        assert nip66_full.rtt_metadata.data.rtt_open == 100
        assert nip66_full.rtt_metadata.data.rtt_read == 150
        assert nip66_full.rtt_metadata.data.rtt_write == 200

    def test_rtt_logs_access(self, nip66_full):
        """Access probe test results via logs attributes."""
        assert nip66_full.rtt_metadata.logs.open_success is True
        assert nip66_full.rtt_metadata.logs.read_success is True
        assert nip66_full.rtt_metadata.logs.write_success is False
        assert nip66_full.rtt_metadata.logs.write_reason == "auth-required: please authenticate"

    def test_ssl_metadata_access(self, nip66_full):
        """Access SSL values via data attributes."""
        assert nip66_full.ssl_metadata.data.ssl_valid is True
        assert nip66_full.ssl_metadata.data.ssl_issuer == "Let's Encrypt"
        assert nip66_full.ssl_metadata.data.ssl_protocol == "TLSv1.3"
        assert nip66_full.ssl_metadata.data.ssl_cipher_bits == 256

    def test_geo_metadata_access(self, nip66_full):
        """Access geo values via data attributes."""
        assert nip66_full.geo_metadata.data.geo_country == "US"
        assert nip66_full.geo_metadata.data.geo_country_name == "United States"
        assert nip66_full.geo_metadata.data.geo_is_eu is False
        assert nip66_full.geo_metadata.data.geohash == "9q9hvu7wp"

    def test_net_metadata_access(self, nip66_full):
        """Access net values via data attributes."""
        assert nip66_full.net_metadata.data.net_ip == "8.8.8.8"
        assert nip66_full.net_metadata.data.net_ipv6 == "2001:4860:4860::8888"
        assert nip66_full.net_metadata.data.net_asn == 15169
        assert nip66_full.net_metadata.data.net_asn_org == "GOOGLE"
        assert nip66_full.net_metadata.data.net_network == "8.8.8.0/24"
        assert nip66_full.net_metadata.data.net_network_v6 == "2001:4860::/32"

    def test_dns_metadata_access(self, nip66_full):
        """Access DNS values via data attributes."""
        assert nip66_full.dns_metadata.data.dns_ips == ["8.8.8.8", "8.8.4.4"]
        assert nip66_full.dns_metadata.data.dns_ips_v6 == ["2001:4860:4860::8888"]
        assert nip66_full.dns_metadata.data.dns_ttl == 300
        assert nip66_full.dns_metadata.data.dns_cname == "dns.google"

    def test_http_metadata_access(self, nip66_full):
        """Access HTTP values via data attributes."""
        assert nip66_full.http_metadata.data.http_server == "nginx/1.24.0"
        assert nip66_full.http_metadata.data.http_powered_by == "Strfry"


class TestDataParsing:
    """Test data parsing and type validation via parse() class method.

    Note: parse() returns a dict (for sanitizing raw input), then the model
    is created from the parsed dict. Tests verify the sanitization logic.
    """

    def test_filters_invalid_rtt_types(self):
        """Invalid types in RTT data are filtered."""
        raw = {
            "rtt_open": "fast",  # Invalid: should be int
            "rtt_read": 150,  # Valid
        }
        parsed = Nip66RttData.parse(raw)
        data = Nip66RttData(**parsed)
        assert data.rtt_open is None
        assert data.rtt_read == 150

    def test_filters_invalid_ssl_types(self):
        """Invalid types in SSL data are filtered."""
        raw = {
            "ssl_valid": "yes",  # Invalid: should be bool
            "ssl_issuer": 123,  # Invalid: should be str
            "ssl_expires": 1735689600,  # Valid
        }
        parsed = Nip66SslData.parse(raw)
        data = Nip66SslData(**parsed)
        assert data.ssl_valid is None
        assert data.ssl_issuer is None
        assert data.ssl_expires == 1735689600

    def test_filters_invalid_geo_types(self):
        """Invalid types in geo data are filtered."""
        raw = {
            "geo_country": "US",  # Valid
            "geo_lat": "37.386",  # Invalid: should be float
            "geo_lon": -122.084,  # Valid
            "geo_geoname_id": "5375480",  # Invalid: should be int
        }
        parsed = Nip66GeoData.parse(raw)
        data = Nip66GeoData(**parsed)
        assert data.geo_country == "US"
        assert data.geo_lat is None
        assert data.geo_lon == -122.084
        assert data.geo_geoname_id is None

    def test_filters_invalid_net_types(self):
        """Invalid types in net data are filtered."""
        raw = {
            "net_ip": 127001,  # Invalid: should be str
            "net_asn": "15169",  # Invalid: should be int
            "net_asn_org": "GOOGLE",  # Valid
            "net_network": 123,  # Invalid: should be str
        }
        parsed = Nip66NetData.parse(raw)
        data = Nip66NetData(**parsed)
        assert data.net_ip is None
        assert data.net_asn is None
        assert data.net_asn_org == "GOOGLE"
        assert data.net_network is None

    def test_preserves_valid_strings(self):
        """Valid strings are preserved (parse() validates types, not content)."""
        raw = {
            "ssl_valid": True,
            "ssl_issuer": "Let's Encrypt",
            "ssl_subject_cn": "example.com",
        }
        parsed = Nip66SslData.parse(raw)
        data = Nip66SslData(**parsed)
        assert data.ssl_valid is True
        assert data.ssl_issuer == "Let's Encrypt"
        assert data.ssl_subject_cn == "example.com"

    def test_filters_empty_lists(self):
        """Empty lists are filtered out."""
        raw = {
            "dns_ttl": 300,
            "dns_ips": [],  # Empty list
            "dns_ns": ["ns1.google.com"],  # Non-empty list
        }
        parsed = Nip66DnsData.parse(raw)
        data = Nip66DnsData(**parsed)
        assert data.dns_ttl == 300
        assert data.dns_ips is None
        assert data.dns_ns == ["ns1.google.com"]

    def test_filters_invalid_list_elements(self):
        """Invalid types inside lists are filtered out."""
        raw = {
            "dns_ttl": 300,
            "dns_ips": ["8.8.8.8", 123, "8.8.4.4"],  # Int mixed in
            "dns_ns": ["ns1.google.com", None, "ns2.google.com"],  # None mixed in
        }
        parsed = Nip66DnsData.parse(raw)
        data = Nip66DnsData(**parsed)
        assert data.dns_ips == ["8.8.8.8", "8.8.4.4"]
        assert data.dns_ns == ["ns1.google.com", "ns2.google.com"]

    def test_list_with_only_invalid_elements_becomes_none(self):
        """List with only invalid elements becomes None."""
        raw = {
            "dns_ttl": 300,
            "dns_ips": [123, 456, 789],  # All invalid
            "dns_ns": [None, None],  # All None
        }
        parsed = Nip66DnsData.parse(raw)
        data = Nip66DnsData(**parsed)
        assert data.dns_ips is None
        assert data.dns_ns is None

    def test_preserves_strings_in_lists(self):
        """String lists preserve all valid strings (parse() validates types, not content)."""
        raw = {
            "dns_ttl": 300,
            "dns_ips": ["8.8.8.8", "8.8.4.4"],
            "dns_ns": ["ns1.google.com", "ns2.google.com"],
        }
        parsed = Nip66DnsData.parse(raw)
        data = Nip66DnsData(**parsed)
        assert data.dns_ips == ["8.8.8.8", "8.8.4.4"]
        assert data.dns_ns == ["ns1.google.com", "ns2.google.com"]


class TestToRelayMetadataTuple:
    """Test to_relay_metadata_tuple() method."""

    def test_returns_named_tuple_of_six(self, nip66_full):
        """Returns RelayNip66MetadataTuple with 6 fields."""
        result = nip66_full.to_relay_metadata_tuple()
        assert isinstance(result, RelayNip66MetadataTuple)
        assert isinstance(result.nip66_rtt, RelayMetadata)
        assert isinstance(result.nip66_ssl, RelayMetadata)
        assert isinstance(result.nip66_geo, RelayMetadata)
        assert isinstance(result.nip66_net, RelayMetadata)
        assert isinstance(result.nip66_dns, RelayMetadata)
        assert isinstance(result.nip66_http, RelayMetadata)

    def test_correct_metadata_types(self, nip66_full):
        """Each RelayMetadata has correct type."""
        result = nip66_full.to_relay_metadata_tuple()
        assert result.nip66_rtt.metadata_type == MetadataType.NIP66_RTT
        assert result.nip66_ssl.metadata_type == MetadataType.NIP66_SSL
        assert result.nip66_geo.metadata_type == MetadataType.NIP66_GEO
        assert result.nip66_net.metadata_type == MetadataType.NIP66_NET
        assert result.nip66_dns.metadata_type == MetadataType.NIP66_DNS
        assert result.nip66_http.metadata_type == MetadataType.NIP66_HTTP

    def test_returns_none_for_missing_metadata(self, nip66_rtt_only):
        """Returns None for missing metadata types."""
        result = nip66_rtt_only.to_relay_metadata_tuple()
        # RTT has data
        assert isinstance(result.nip66_rtt, RelayMetadata)
        assert result.nip66_rtt.metadata.metadata["data"]["rtt_open"] == 100
        # Others are None
        assert result.nip66_ssl is None
        assert result.nip66_geo is None
        assert result.nip66_net is None
        assert result.nip66_dns is None
        assert result.nip66_http is None

    def test_preserves_relay(self, nip66_full):
        """Each RelayMetadata preserves relay reference."""
        result = nip66_full.to_relay_metadata_tuple()
        assert result.nip66_rtt.relay is nip66_full.relay
        assert result.nip66_ssl.relay is nip66_full.relay
        assert result.nip66_geo.relay is nip66_full.relay
        assert result.nip66_net.relay is nip66_full.relay
        assert result.nip66_dns.relay is nip66_full.relay
        assert result.nip66_http.relay is nip66_full.relay

    def test_preserves_generated_at(self, nip66_full):
        """Each RelayMetadata preserves generated_at timestamp."""
        result = nip66_full.to_relay_metadata_tuple()
        assert result.nip66_rtt.generated_at == 1234567890
        assert result.nip66_ssl.generated_at == 1234567890
        assert result.nip66_geo.generated_at == 1234567890
        assert result.nip66_net.generated_at == 1234567890
        assert result.nip66_dns.generated_at == 1234567890
        assert result.nip66_http.generated_at == 1234567890


class TestSslMetadataMethod:
    """Test Nip66SslMetadata._ssl() static method."""

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

                result = Nip66SslMetadata._ssl("example.com", 443, 30.0)

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
                result = Nip66SslMetadata._ssl("example.com", 443, 30.0)

        assert result.get("ssl_valid") is False

    def test_connection_error_returns_dict_with_ssl_valid_false(self):
        """Connection error is handled internally and returns dict with ssl_valid=False."""
        with patch("socket.create_connection", side_effect=TimeoutError()):
            result = Nip66SslMetadata._ssl("example.com", 443, 30.0)

        assert result.get("ssl_valid") is False


class TestGeoMetadataMethod:
    """Test Nip66GeoMetadata._geo() static method."""

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

        result = Nip66GeoMetadata._geo("8.8.8.8", mock_city_reader)

        assert "geo_ip" not in result
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


class TestNetMetadataMethod:
    """Test Nip66NetMetadata._net() static method."""

    def test_success_with_ipv4_only(self):
        """Successful lookup with IPv4 only returns net data."""
        mock_asn_response = MagicMock()
        mock_asn_response.autonomous_system_number = 7922
        mock_asn_response.autonomous_system_organization = "Comcast Cable"
        mock_asn_response.network = "1.2.3.0/24"

        mock_asn_reader = MagicMock()
        mock_asn_reader.asn.return_value = mock_asn_response

        result = Nip66NetMetadata._net("8.8.8.8", None, mock_asn_reader)

        assert result["net_ip"] == "8.8.8.8"
        assert result.get("net_ipv6") is None
        assert result["net_asn"] == 7922
        assert result["net_asn_org"] == "Comcast Cable"
        assert result["net_network"] == "1.2.3.0/24"
        assert result.get("net_network_v6") is None

    def test_success_with_ipv6_only(self):
        """Successful lookup with IPv6 only returns net data."""
        mock_asn_response = MagicMock()
        mock_asn_response.autonomous_system_number = 15169
        mock_asn_response.autonomous_system_organization = "GOOGLE"
        mock_asn_response.network = "2001:4860::/32"

        mock_asn_reader = MagicMock()
        mock_asn_reader.asn.return_value = mock_asn_response

        result = Nip66NetMetadata._net(None, "2001:4860:4860::8888", mock_asn_reader)

        assert result.get("net_ip") is None
        assert result["net_ipv6"] == "2001:4860:4860::8888"
        assert result["net_asn"] == 15169
        assert result["net_asn_org"] == "GOOGLE"
        assert result.get("net_network") is None
        assert result["net_network_v6"] == "2001:4860::/32"

    def test_success_with_dual_stack(self):
        """Successful lookup with both IPv4 and IPv6 returns full net data."""
        mock_asn_response_v4 = MagicMock()
        mock_asn_response_v4.autonomous_system_number = 15169
        mock_asn_response_v4.autonomous_system_organization = "GOOGLE"
        mock_asn_response_v4.network = "8.8.8.0/24"

        mock_asn_response_v6 = MagicMock()
        mock_asn_response_v6.autonomous_system_number = 15169
        mock_asn_response_v6.autonomous_system_organization = "GOOGLE"
        mock_asn_response_v6.network = "2001:4860::/32"

        mock_asn_reader = MagicMock()
        mock_asn_reader.asn.side_effect = [mock_asn_response_v4, mock_asn_response_v6]

        result = Nip66NetMetadata._net("8.8.8.8", "2001:4860:4860::8888", mock_asn_reader)

        assert result["net_ip"] == "8.8.8.8"
        assert result["net_ipv6"] == "2001:4860:4860::8888"
        assert result["net_asn"] == 15169
        assert result["net_asn_org"] == "GOOGLE"
        assert result["net_network"] == "8.8.8.0/24"
        assert result["net_network_v6"] == "2001:4860::/32"


class TestDnsMetadataMethod:
    """Test Nip66DnsMetadata._dns() static method."""

    def test_success_returns_dns_data(self):
        """Successful DNS resolution returns comprehensive data."""
        mock_a_response = MagicMock()
        mock_a_response.__iter__ = lambda _: iter([MagicMock(address="8.8.8.8")])
        mock_a_response.rrset.ttl = 300

        mock_resolver = MagicMock()
        mock_resolver.resolve.return_value = mock_a_response

        with patch("dns.resolver.Resolver", return_value=mock_resolver):
            result = Nip66DnsMetadata._dns("example.com", 5.0)

        assert result.get("dns_ips") == ["8.8.8.8"]
        assert result.get("dns_ttl") == 300


class TestSslAsyncMethod:
    """Test Nip66SslMetadata.ssl() async class method."""

    @pytest.mark.asyncio
    async def test_clearnet_wss_returns_ssl_metadata(self, relay):
        """Returns Nip66SslMetadata for clearnet wss:// relay."""
        ssl_result = {
            "ssl_valid": True,
            "ssl_issuer": "Test CA",
            "ssl_protocol": "TLSv1.3",
        }

        with patch.object(Nip66SslMetadata, "_ssl", return_value=ssl_result):
            result = await Nip66SslMetadata.ssl(relay, 10.0)

        assert isinstance(result, Nip66SslMetadata)
        assert result.data.ssl_valid is True
        assert result.data.ssl_protocol == "TLSv1.3"

    @pytest.mark.asyncio
    async def test_ssl_failure_returns_metadata_with_failure(self, relay):
        """SSL check failure returns Nip66SslMetadata with success=False."""
        with patch.object(Nip66SslMetadata, "_ssl", return_value={}):
            result = await Nip66SslMetadata.ssl(relay, 10.0)
        assert isinstance(result, Nip66SslMetadata)
        assert result.logs.success is False
        assert result.logs.reason is not None

    @pytest.mark.asyncio
    async def test_tor_raises_value_error(self, tor_relay):
        """Raises ValueError for Tor relay (SSL not applicable)."""
        with pytest.raises(ValueError, match="SSL test requires clearnet"):
            await Nip66SslMetadata.ssl(tor_relay, 10.0)


class TestGeoAsyncMethod:
    """Test Nip66GeoMetadata.geo() async class method."""

    @pytest.mark.asyncio
    async def test_clearnet_with_reader_returns_geo_metadata(self, relay):
        """Returns Nip66GeoMetadata for clearnet relay with city reader."""
        geo_result = {
            "geo_country": "US",
            "geo_country_name": "United States",
        }

        mock_city_reader = MagicMock()

        with (
            patch("socket.gethostbyname", return_value="8.8.8.8"),
            patch.object(Nip66GeoMetadata, "_geo", return_value=geo_result),
        ):
            result = await Nip66GeoMetadata.geo(relay, mock_city_reader)

        assert isinstance(result, Nip66GeoMetadata)
        assert result.data.geo_country == "US"

    @pytest.mark.asyncio
    async def test_tor_raises_value_error(self, tor_relay):
        """Raises ValueError for Tor relay (geo not applicable)."""
        mock_city_reader = MagicMock()
        with pytest.raises(ValueError, match="geo lookup requires clearnet"):
            await Nip66GeoMetadata.geo(tor_relay, mock_city_reader)


class TestNetAsyncMethod:
    """Test Nip66NetMetadata.net() async class method."""

    @pytest.mark.asyncio
    async def test_clearnet_with_reader_returns_net_metadata(self, relay):
        """Returns Nip66NetMetadata for clearnet relay with ASN reader."""
        net_result = {
            "net_ip": "8.8.8.8",
            "net_ipv6": "2001:4860:4860::8888",
            "net_asn": 15169,
            "net_asn_org": "GOOGLE",
            "net_network": "8.8.8.0/24",
            "net_network_v6": "2001:4860::/32",
        }

        mock_asn_reader = MagicMock()
        mock_ipv6_result = [(None, None, None, None, ("2001:4860:4860::8888", 0, 0, 0))]

        with (
            patch("socket.gethostbyname", return_value="8.8.8.8"),
            patch("socket.getaddrinfo", return_value=mock_ipv6_result),
            patch.object(Nip66NetMetadata, "_net", return_value=net_result),
        ):
            result = await Nip66NetMetadata.net(relay, mock_asn_reader)

        assert isinstance(result, Nip66NetMetadata)
        assert result.data.net_asn == 15169
        assert result.data.net_ip == "8.8.8.8"
        assert result.data.net_ipv6 == "2001:4860:4860::8888"

    @pytest.mark.asyncio
    async def test_tor_raises_value_error(self, tor_relay):
        """Raises ValueError for Tor relay (net not applicable)."""
        mock_asn_reader = MagicMock()
        with pytest.raises(ValueError, match="net lookup requires clearnet"):
            await Nip66NetMetadata.net(tor_relay, mock_asn_reader)


class TestDnsAsyncMethod:
    """Test Nip66DnsMetadata.dns() async class method."""

    @pytest.mark.asyncio
    async def test_clearnet_returns_dns_metadata(self, relay):
        """Returns Nip66DnsMetadata for clearnet relay."""
        dns_result = {
            "dns_ips": ["8.8.8.8"],
            "dns_ttl": 300,
        }

        with patch.object(Nip66DnsMetadata, "_dns", return_value=dns_result):
            result = await Nip66DnsMetadata.dns(relay, 5.0)

        assert isinstance(result, Nip66DnsMetadata)
        assert result.data.dns_ips == ["8.8.8.8"]
        assert result.data.dns_ttl == 300

    @pytest.mark.asyncio
    async def test_tor_raises_value_error(self, tor_relay):
        """Raises ValueError for Tor relay (DNS not applicable)."""
        with pytest.raises(ValueError, match="DNS resolve requires clearnet"):
            await Nip66DnsMetadata.dns(tor_relay, 5.0)


class TestHttpAsyncMethod:
    """Test Nip66HttpMetadata.http() async class method."""

    @pytest.mark.asyncio
    async def test_clearnet_returns_http_metadata(self, relay):
        """Returns Nip66HttpMetadata for clearnet relay."""
        http_result = {
            "http_server": "nginx/1.24.0",
            "http_powered_by": "Strfry",
        }

        async def mock_check_http(*args, **kwargs):
            return http_result

        with patch.object(Nip66HttpMetadata, "_http", mock_check_http):
            result = await Nip66HttpMetadata.http(relay, 10.0)

        assert isinstance(result, Nip66HttpMetadata)
        assert result.data.http_server == "nginx/1.24.0"

    @pytest.mark.asyncio
    async def test_tor_without_proxy_raises_value_error(self, tor_relay):
        """Raises ValueError for Tor relay without proxy."""
        with pytest.raises(ValueError, match=r"overlay network .* requires proxy"):
            await Nip66HttpMetadata.http(tor_relay, 10.0)


class TestRttAsyncMethod:
    """Test Nip66RttMetadata.rtt() async class method."""

    @pytest.mark.asyncio
    async def test_clearnet_returns_rtt_metadata(self, relay, mock_keys, mock_nostr_client):
        """Returns Nip66RttMetadata for clearnet relay."""
        mock_event_builder = MagicMock()
        mock_read_filter = MagicMock()

        async def mock_connect_relay(
            relay, keys=None, proxy_url=None, timeout=10.0, allow_insecure=True
        ):
            return mock_nostr_client

        with patch("utils.transport.connect_relay", side_effect=mock_connect_relay):
            result = await Nip66RttMetadata.rtt(
                relay,
                mock_keys,
                mock_event_builder,
                mock_read_filter,
                timeout=10.0,
            )

        assert isinstance(result, Nip66RttMetadata)
        assert result.data.rtt_open is not None
        assert result.logs.open_success is True

    @pytest.mark.asyncio
    async def test_connection_failure_returns_rtt_with_failure_logs(self, relay, mock_keys):
        """Connection failure returns Nip66RttMetadata with failure logged."""
        mock_event_builder = MagicMock()
        mock_read_filter = MagicMock()

        async def mock_connect_relay(
            relay, keys=None, proxy_url=None, timeout=10.0, allow_insecure=True
        ):
            raise TimeoutError("Connection refused")

        with patch("utils.transport.connect_relay", side_effect=mock_connect_relay):
            result = await Nip66RttMetadata.rtt(
                relay,
                mock_keys,
                mock_event_builder,
                mock_read_filter,
                timeout=10.0,
            )

        assert isinstance(result, Nip66RttMetadata)
        assert result.logs.open_success is False
        assert "Connection refused" in (result.logs.open_reason or "")


class TestCreate:
    """Test Nip66.create() class method."""

    @pytest.mark.asyncio
    async def test_returns_nip66_on_success(self, relay, mock_keys, mock_nostr_client):
        """Returns Nip66 instance on successful create."""
        rtt_metadata = Nip66RttMetadata(
            data=Nip66RttData(rtt_open=100, rtt_read=150),
            logs=Nip66RttLogs(open_success=True, read_success=True),
        )
        dns_metadata = Nip66DnsMetadata(
            data=Nip66DnsData(dns_ips=["8.8.8.8"], dns_ttl=300),
            logs=Nip66DnsLogs(success=True, reason=None),
        )

        mock_event_builder = MagicMock()
        mock_read_filter = MagicMock()

        with (
            patch.object(
                Nip66DnsMetadata, "dns", new_callable=AsyncMock, return_value=dns_metadata
            ),
            patch.object(
                Nip66RttMetadata, "rtt", new_callable=AsyncMock, return_value=rtt_metadata
            ),
            patch.object(Nip66SslMetadata, "ssl", new_callable=AsyncMock, return_value=None),
            patch.object(Nip66GeoMetadata, "geo", new_callable=AsyncMock, return_value=None),
            patch.object(Nip66NetMetadata, "net", new_callable=AsyncMock, return_value=None),
            patch.object(Nip66HttpMetadata, "http", new_callable=AsyncMock, return_value=None),
        ):
            result = await Nip66.create(
                relay,
                keys=mock_keys,
                event_builder=mock_event_builder,
                read_filter=mock_read_filter,
            )

        assert isinstance(result, Nip66)
        assert result.rtt_metadata.data.rtt_open == 100
        assert result.rtt_metadata.logs.open_success is True
        assert result.dns_metadata.data.dns_ips == ["8.8.8.8"]

    @pytest.mark.asyncio
    async def test_all_tests_fail_returns_nip66_with_none_metadata(self, relay, mock_keys):
        """All tests failing returns Nip66 with None metadata."""
        mock_event_builder = MagicMock()
        mock_read_filter = MagicMock()

        with (
            patch.object(Nip66DnsMetadata, "dns", new_callable=AsyncMock, return_value=None),
            patch.object(Nip66RttMetadata, "rtt", new_callable=AsyncMock, return_value=None),
            patch.object(Nip66SslMetadata, "ssl", new_callable=AsyncMock, return_value=None),
            patch.object(Nip66GeoMetadata, "geo", new_callable=AsyncMock, return_value=None),
            patch.object(Nip66NetMetadata, "net", new_callable=AsyncMock, return_value=None),
            patch.object(Nip66HttpMetadata, "http", new_callable=AsyncMock, return_value=None),
        ):
            result = await Nip66.create(
                relay,
                keys=mock_keys,
                event_builder=mock_event_builder,
                read_filter=mock_read_filter,
            )

        assert isinstance(result, Nip66)
        assert result.rtt_metadata is None
        assert result.ssl_metadata is None
        assert result.geo_metadata is None
        assert result.net_metadata is None
        assert result.dns_metadata is None
        assert result.http_metadata is None

    @pytest.mark.asyncio
    async def test_rtt_skipped_without_keys(self, relay):
        """run_rtt=True without keys/event_builder/read_filter skips RTT."""
        result = await Nip66.create(
            relay,
            run_rtt=True,
            run_ssl=False,
            run_geo=False,
            run_net=False,
            run_dns=False,
            run_http=False,
            keys=None,
            event_builder=None,
            read_filter=None,
        )
        assert isinstance(result, Nip66)
        assert result.rtt_metadata is None

    @pytest.mark.asyncio
    async def test_can_skip_all_except_dns(self, relay):
        """Can skip all tests except DNS."""
        dns_metadata = Nip66DnsMetadata(
            data=Nip66DnsData(dns_ips=["8.8.8.8"], dns_ttl=300),
            logs=Nip66DnsLogs(success=True, reason=None),
        )

        with patch.object(
            Nip66DnsMetadata, "dns", new_callable=AsyncMock, return_value=dns_metadata
        ):
            result = await Nip66.create(
                relay, run_rtt=False, run_ssl=False, run_geo=False, run_net=False, run_http=False
            )

        assert isinstance(result, Nip66)
        assert result.dns_metadata.data.dns_ips == ["8.8.8.8"]
        assert result.dns_metadata.data.dns_ttl == 300
        assert result.rtt_metadata is None
        assert result.ssl_metadata is None
        assert result.geo_metadata is None
        assert result.net_metadata is None
        assert result.http_metadata is None
