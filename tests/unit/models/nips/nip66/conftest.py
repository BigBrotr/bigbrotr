"""
Shared fixtures for NIP-66 module tests.

Provides:
- Relay fixtures (clearnet, tor, ws://)
- Complete metadata fixtures for all NIP-66 types
- Mock fixtures for nostr-sdk, GeoIP, and ASN readers
- Helper fixtures for building test data
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from models import Relay
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
)


# =============================================================================
# Relay Fixtures
# =============================================================================


@pytest.fixture
def relay() -> Relay:
    """Create a clearnet test relay (wss://)."""
    return Relay(raw_url="wss://relay.example.com", discovered_at=1234567890)


@pytest.fixture
def relay_with_port() -> Relay:
    """Create a clearnet relay with explicit port."""
    return Relay(raw_url="wss://relay.example.com:8443", discovered_at=1234567890)


@pytest.fixture
def tor_relay() -> Relay:
    """Create a Tor relay (.onion)."""
    return Relay(raw_url="wss://abcdef1234567890.onion", discovered_at=1234567890)


@pytest.fixture
def i2p_relay() -> Relay:
    """Create an I2P relay (.i2p)."""
    return Relay(raw_url="wss://example.i2p", discovered_at=1234567890)


@pytest.fixture
def loki_relay() -> Relay:
    """Create a Lokinet relay (.loki)."""
    return Relay(raw_url="wss://example.loki", discovered_at=1234567890)


@pytest.fixture
def ws_relay() -> Relay:
    """Create a ws:// relay (no SSL)."""
    return Relay(raw_url="ws://relay.example.com", discovered_at=1234567890)


# =============================================================================
# RTT Metadata Fixtures
# =============================================================================


@pytest.fixture
def complete_rtt_data() -> Nip66RttData:
    """Complete RTT data with all timing values."""
    return Nip66RttData(rtt_open=100, rtt_read=150, rtt_write=200)


@pytest.fixture
def complete_rtt_logs() -> Nip66RttLogs:
    """Complete RTT logs with partial success (write failed)."""
    return Nip66RttLogs(
        open_success=True,
        open_reason=None,
        read_success=True,
        read_reason=None,
        write_success=False,
        write_reason="auth-required: please authenticate",
    )


@pytest.fixture
def complete_rtt_metadata(
    complete_rtt_data: Nip66RttData,
    complete_rtt_logs: Nip66RttLogs,
) -> Nip66RttMetadata:
    """Complete RTT metadata with data and logs."""
    return Nip66RttMetadata(data=complete_rtt_data, logs=complete_rtt_logs)


@pytest.fixture
def rtt_all_success_logs() -> Nip66RttLogs:
    """RTT logs with all operations successful."""
    return Nip66RttLogs(
        open_success=True,
        read_success=True,
        write_success=True,
    )


@pytest.fixture
def rtt_open_failed_logs() -> Nip66RttLogs:
    """RTT logs with open failure cascading to read/write."""
    return Nip66RttLogs(
        open_success=False,
        open_reason="connection refused",
        read_success=False,
        read_reason="connection refused",
        write_success=False,
        write_reason="connection refused",
    )


# =============================================================================
# SSL Metadata Fixtures
# =============================================================================


@pytest.fixture
def complete_ssl_data() -> Nip66SslData:
    """Complete SSL data with all certificate fields."""
    return Nip66SslData(
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
    )


@pytest.fixture
def complete_ssl_logs() -> Nip66SslLogs:
    """Complete SSL logs indicating success."""
    return Nip66SslLogs(success=True, reason=None)


@pytest.fixture
def complete_ssl_metadata(
    complete_ssl_data: Nip66SslData,
    complete_ssl_logs: Nip66SslLogs,
) -> Nip66SslMetadata:
    """Complete SSL metadata with data and logs."""
    return Nip66SslMetadata(data=complete_ssl_data, logs=complete_ssl_logs)


# =============================================================================
# Geo Metadata Fixtures
# =============================================================================


@pytest.fixture
def complete_geo_data() -> Nip66GeoData:
    """Complete geo data with all location fields."""
    return Nip66GeoData(
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


@pytest.fixture
def complete_geo_logs() -> Nip66GeoLogs:
    """Complete geo logs indicating success."""
    return Nip66GeoLogs(success=True, reason=None)


@pytest.fixture
def complete_geo_metadata(
    complete_geo_data: Nip66GeoData,
    complete_geo_logs: Nip66GeoLogs,
) -> Nip66GeoMetadata:
    """Complete geo metadata with data and logs."""
    return Nip66GeoMetadata(data=complete_geo_data, logs=complete_geo_logs)


# =============================================================================
# Net Metadata Fixtures
# =============================================================================


@pytest.fixture
def complete_net_data() -> Nip66NetData:
    """Complete net data with all ASN fields."""
    return Nip66NetData(
        net_ip="8.8.8.8",
        net_ipv6="2001:4860:4860::8888",
        net_asn=15169,
        net_asn_org="GOOGLE",
        net_network="8.8.8.0/24",
        net_network_v6="2001:4860::/32",
    )


@pytest.fixture
def complete_net_logs() -> Nip66NetLogs:
    """Complete net logs indicating success."""
    return Nip66NetLogs(success=True, reason=None)


@pytest.fixture
def complete_net_metadata(
    complete_net_data: Nip66NetData,
    complete_net_logs: Nip66NetLogs,
) -> Nip66NetMetadata:
    """Complete net metadata with data and logs."""
    return Nip66NetMetadata(data=complete_net_data, logs=complete_net_logs)


# =============================================================================
# DNS Metadata Fixtures
# =============================================================================


@pytest.fixture
def complete_dns_data() -> Nip66DnsData:
    """Complete DNS data with all record types."""
    return Nip66DnsData(
        dns_ips=["8.8.8.8", "8.8.4.4"],
        dns_ips_v6=["2001:4860:4860::8888"],
        dns_cname="dns.google",
        dns_reverse="dns.google",
        dns_ns=["ns1.google.com", "ns2.google.com"],
        dns_ttl=300,
    )


@pytest.fixture
def complete_dns_logs() -> Nip66DnsLogs:
    """Complete DNS logs indicating success."""
    return Nip66DnsLogs(success=True, reason=None)


@pytest.fixture
def complete_dns_metadata(
    complete_dns_data: Nip66DnsData,
    complete_dns_logs: Nip66DnsLogs,
) -> Nip66DnsMetadata:
    """Complete DNS metadata with data and logs."""
    return Nip66DnsMetadata(data=complete_dns_data, logs=complete_dns_logs)


# =============================================================================
# HTTP Metadata Fixtures
# =============================================================================


@pytest.fixture
def complete_http_data() -> Nip66HttpData:
    """Complete HTTP data with server headers."""
    return Nip66HttpData(
        http_server="nginx/1.24.0",
        http_powered_by="Strfry",
    )


@pytest.fixture
def complete_http_logs() -> Nip66HttpLogs:
    """Complete HTTP logs indicating success."""
    return Nip66HttpLogs(success=True, reason=None)


@pytest.fixture
def complete_http_metadata(
    complete_http_data: Nip66HttpData,
    complete_http_logs: Nip66HttpLogs,
) -> Nip66HttpMetadata:
    """Complete HTTP metadata with data and logs."""
    return Nip66HttpMetadata(data=complete_http_data, logs=complete_http_logs)


# =============================================================================
# Full Nip66 Fixtures
# =============================================================================


@pytest.fixture
def nip66_full(
    relay: Relay,
    complete_rtt_metadata: Nip66RttMetadata,
    complete_ssl_metadata: Nip66SslMetadata,
    complete_geo_metadata: Nip66GeoMetadata,
    complete_net_metadata: Nip66NetMetadata,
    complete_dns_metadata: Nip66DnsMetadata,
    complete_http_metadata: Nip66HttpMetadata,
) -> Nip66:
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
def nip66_rtt_only(relay: Relay, complete_rtt_metadata: Nip66RttMetadata) -> Nip66:
    """Nip66 instance with only RTT metadata."""
    return Nip66(
        relay=relay,
        rtt_metadata=complete_rtt_metadata,
        generated_at=1234567890,
    )


@pytest.fixture
def nip66_dns_only(relay: Relay, complete_dns_metadata: Nip66DnsMetadata) -> Nip66:
    """Nip66 instance with only DNS metadata."""
    return Nip66(
        relay=relay,
        dns_metadata=complete_dns_metadata,
        generated_at=1234567890,
    )


# =============================================================================
# Mock Fixtures - nostr-sdk
# =============================================================================


@pytest.fixture
def mock_keys() -> MagicMock:
    """Mock nostr_sdk.Keys object for RTT tests."""
    keys = MagicMock()
    keys._inner = MagicMock()
    return keys


@pytest.fixture
def mock_event_builder() -> MagicMock:
    """Mock nostr_sdk.EventBuilder for RTT write tests."""
    return MagicMock()


@pytest.fixture
def mock_read_filter() -> MagicMock:
    """Mock nostr_sdk.Filter for RTT read tests."""
    return MagicMock()


@pytest.fixture
def mock_nostr_client() -> MagicMock:
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
    mock_output.failed = {}
    mock_output.id = MagicMock()
    mock_client.send_event_builder = AsyncMock(return_value=mock_output)
    return mock_client


# =============================================================================
# Mock Fixtures - GeoIP and ASN Readers
# =============================================================================


@pytest.fixture
def mock_city_reader() -> MagicMock:
    """Mock geoip2 City database reader."""
    reader = MagicMock()
    return reader


@pytest.fixture
def mock_asn_reader() -> MagicMock:
    """Mock geoip2 ASN database reader."""
    reader = MagicMock()
    return reader


@pytest.fixture
def mock_geoip_response() -> MagicMock:
    """Mock GeoIP2 City response with complete data."""
    response = MagicMock()
    response.country.iso_code = "US"
    response.country.name = "United States"
    response.country.is_in_european_union = False
    response.registered_country.iso_code = None
    response.registered_country.name = None
    response.continent.code = "NA"
    response.continent.name = "North America"
    response.city.name = "Mountain View"
    response.city.geoname_id = 5375480
    response.postal.code = "94035"
    response.location.latitude = 37.386
    response.location.longitude = -122.084
    response.location.accuracy_radius = 10
    response.location.time_zone = "America/Los_Angeles"
    response.subdivisions.most_specific.name = "California"
    return response


@pytest.fixture
def mock_asn_response() -> MagicMock:
    """Mock GeoIP2 ASN response with complete data."""
    response = MagicMock()
    response.autonomous_system_number = 15169
    response.autonomous_system_organization = "GOOGLE"
    response.network = "8.8.8.0/24"
    return response


# =============================================================================
# SSL Certificate Fixtures
# =============================================================================


@pytest.fixture
def mock_certificate_dict() -> dict[str, Any]:
    """Mock X509 certificate dictionary as returned by getpeercert()."""
    return {
        "subject": ((("commonName", "relay.example.com"),),),
        "issuer": (
            (("organizationName", "Let's Encrypt"),),
            (("commonName", "R3"),),
        ),
        "notAfter": "Dec 31 23:59:59 2024 GMT",
        "notBefore": "Jan  1 00:00:00 2024 GMT",
        "subjectAltName": (
            ("DNS", "relay.example.com"),
            ("DNS", "*.example.com"),
        ),
        "serialNumber": "04ABCDEF12345678",  # pragma: allowlist secret
        "version": 3,
    }


@pytest.fixture
def mock_certificate_binary() -> bytes:
    """Mock binary certificate data for fingerprint tests."""
    return b"mock_certificate_binary_data_for_testing"


# =============================================================================
# DNS Fixtures
# =============================================================================


@pytest.fixture
def mock_dns_a_response() -> MagicMock:
    """Mock DNS A record response."""
    response = MagicMock()
    mock_rdata = MagicMock()
    mock_rdata.address = "8.8.8.8"
    response.__iter__ = lambda _: iter([mock_rdata])
    response.rrset = MagicMock()
    response.rrset.ttl = 300
    return response


@pytest.fixture
def mock_dns_aaaa_response() -> MagicMock:
    """Mock DNS AAAA record response."""
    response = MagicMock()
    mock_rdata = MagicMock()
    mock_rdata.address = "2001:4860:4860::8888"
    response.__iter__ = lambda _: iter([mock_rdata])
    return response
