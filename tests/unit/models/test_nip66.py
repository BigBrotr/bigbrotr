"""
Unit tests for models.nip66 module.

Tests:
- Nip66 construction and validation
- RTT property accessors (rtt_open, rtt_read, rtt_write, rtt_dns)
- SSL property accessors (ssl_valid, ssl_issuer, ssl_expires)
- Geo property accessors (geo_ip, geo_country, geo_city, geohash, etc.)
- Boolean capability flags (is_openable, is_readable, is_writable)
- to_relay_metadata() conversion (generates up to 3 records)
- Internal helper methods (_resolve_dns_sync, _check_ssl_sync, _lookup_geo_sync)
- Nip66.test() async connection tests
"""

import socket
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
        "rtt_dns": 50,
    }


@pytest.fixture
def complete_ssl_data():
    """Complete SSL metadata."""
    return {
        "ssl_valid": True,
        "ssl_issuer": "Let's Encrypt",
        "ssl_expires": 1735689600,
    }


@pytest.fixture
def complete_geo_data():
    """Complete geo metadata."""
    return {
        "geo_ip": "8.8.8.8",
        "geo_country": "US",
        "geo_region": "California",
        "geo_city": "Mountain View",
        "geo_lat": 37.386,
        "geo_lon": -122.084,
        "geo_tz": "America/Los_Angeles",
        "geohash": "9q9hvu7wp",
        "geo_asn": 15169,
        "geo_asn_org": "GOOGLE",
    }


@pytest.fixture
def nip66_full(relay, complete_rtt_data, complete_ssl_data, complete_geo_data):
    """Nip66 with all metadata types."""
    return Nip66(
        relay=relay,
        rtt_metadata=Metadata(complete_rtt_data),
        ssl_metadata=Metadata(complete_ssl_data),
        geo_metadata=Metadata(complete_geo_data),
        generated_at=1234567890,
    )


@pytest.fixture
def nip66_rtt_only(relay, complete_rtt_data):
    """Nip66 with RTT metadata only."""
    return Nip66(
        relay=relay,
        rtt_metadata=Metadata(complete_rtt_data),
        generated_at=1234567890,
    )


class TestConstruction:
    """Test Nip66 construction and validation."""

    def test_with_all_metadata(
        self, relay, complete_rtt_data, complete_ssl_data, complete_geo_data
    ):
        """Construct with all three metadata types."""
        nip66 = Nip66(
            relay=relay,
            rtt_metadata=Metadata(complete_rtt_data),
            ssl_metadata=Metadata(complete_ssl_data),
            geo_metadata=Metadata(complete_geo_data),
        )
        assert nip66.relay is relay
        assert nip66.rtt_metadata is not None
        assert nip66.ssl_metadata is not None
        assert nip66.geo_metadata is not None

    def test_with_rtt_only(self, relay, complete_rtt_data):
        """Construct with RTT metadata only."""
        nip66 = Nip66(relay=relay, rtt_metadata=Metadata(complete_rtt_data))
        assert nip66.rtt_metadata is not None
        assert nip66.ssl_metadata is None
        assert nip66.geo_metadata is None

    def test_with_ssl_only(self, relay, complete_ssl_data):
        """Construct with SSL metadata only."""
        nip66 = Nip66(relay=relay, ssl_metadata=Metadata(complete_ssl_data))
        assert nip66.rtt_metadata is None
        assert nip66.ssl_metadata is not None
        assert nip66.geo_metadata is None

    def test_with_geo_only(self, relay, complete_geo_data):
        """Construct with geo metadata only."""
        nip66 = Nip66(relay=relay, geo_metadata=Metadata(complete_geo_data))
        assert nip66.rtt_metadata is None
        assert nip66.ssl_metadata is None
        assert nip66.geo_metadata is not None

    def test_no_metadata_raises_error(self, relay):
        """Construction without any metadata raises ValueError."""
        with pytest.raises(ValueError, match="At least one metadata"):
            Nip66(relay=relay)

    def test_empty_metadata_becomes_none(self, relay, complete_rtt_data):
        """Empty metadata dict becomes None after parsing."""
        nip66 = Nip66(
            relay=relay,
            rtt_metadata=Metadata(complete_rtt_data),
            ssl_metadata=Metadata({}),  # Empty
            geo_metadata=Metadata({}),  # Empty
        )
        assert nip66.rtt_metadata is not None
        assert nip66.ssl_metadata is None
        assert nip66.geo_metadata is None

    def test_generated_at_default(self, relay, complete_rtt_data):
        """generated_at defaults to current time."""
        nip66 = Nip66(relay=relay, rtt_metadata=Metadata(complete_rtt_data))
        assert nip66.generated_at > 0

    def test_generated_at_explicit(self, relay, complete_rtt_data):
        """Explicit generated_at is preserved."""
        nip66 = Nip66(relay=relay, rtt_metadata=Metadata(complete_rtt_data), generated_at=1000)
        assert nip66.generated_at == 1000


class TestRttProperties:
    """Test RTT property accessors."""

    def test_all_rtt_values(self, nip66_full):
        """Access all RTT values."""
        assert nip66_full.rtt_open == 100
        assert nip66_full.rtt_read == 150
        assert nip66_full.rtt_write == 200
        assert nip66_full.rtt_dns == 50

    def test_missing_rtt_metadata(self, relay, complete_ssl_data):
        """Missing RTT metadata returns None for all RTT properties."""
        nip66 = Nip66(relay=relay, ssl_metadata=Metadata(complete_ssl_data))
        assert nip66.rtt_open is None
        assert nip66.rtt_read is None
        assert nip66.rtt_write is None
        assert nip66.rtt_dns is None

    def test_partial_rtt_data(self, relay):
        """Partial RTT data returns None for missing fields."""
        nip66 = Nip66(relay=relay, rtt_metadata=Metadata({"rtt_open": 100}))
        assert nip66.rtt_open == 100
        assert nip66.rtt_read is None
        assert nip66.rtt_write is None
        assert nip66.rtt_dns is None

    def test_has_rtt(self, nip66_full, relay, complete_ssl_data):
        """has_rtt property."""
        assert nip66_full.has_rtt is True
        nip66_no_rtt = Nip66(relay=relay, ssl_metadata=Metadata(complete_ssl_data))
        assert nip66_no_rtt.has_rtt is False


class TestCapabilityFlags:
    """Test capability boolean flags."""

    def test_is_openable(self, nip66_full):
        """is_openable returns True when rtt_open is present."""
        assert nip66_full.is_openable is True

    def test_is_readable(self, nip66_full):
        """is_readable returns True when rtt_read is present."""
        assert nip66_full.is_readable is True

    def test_is_writable(self, nip66_full):
        """is_writable returns True when rtt_write is present."""
        assert nip66_full.is_writable is True

    def test_capability_flags_partial(self, relay):
        """Capability flags with partial data."""
        nip66 = Nip66(relay=relay, rtt_metadata=Metadata({"rtt_open": 100, "rtt_read": 150}))
        assert nip66.is_openable is True
        assert nip66.is_readable is True
        assert nip66.is_writable is False

    def test_capability_flags_no_rtt(self, relay, complete_ssl_data):
        """Capability flags return False when no RTT metadata."""
        nip66 = Nip66(relay=relay, ssl_metadata=Metadata(complete_ssl_data))
        assert nip66.is_openable is False
        assert nip66.is_readable is False
        assert nip66.is_writable is False


class TestSslProperties:
    """Test SSL property accessors."""

    def test_all_ssl_values(self, nip66_full):
        """Access all SSL values."""
        assert nip66_full.ssl_valid is True
        assert nip66_full.ssl_issuer == "Let's Encrypt"
        assert nip66_full.ssl_expires == 1735689600

    def test_missing_ssl_metadata(self, nip66_rtt_only):
        """Missing SSL metadata returns None for all SSL properties."""
        assert nip66_rtt_only.ssl_valid is None
        assert nip66_rtt_only.ssl_issuer is None
        assert nip66_rtt_only.ssl_expires is None

    def test_has_ssl(self, nip66_full, nip66_rtt_only):
        """has_ssl property."""
        assert nip66_full.has_ssl is True
        assert nip66_rtt_only.has_ssl is False


class TestGeoProperties:
    """Test geo property accessors."""

    def test_all_geo_values(self, nip66_full):
        """Access all geo values."""
        assert nip66_full.geo_ip == "8.8.8.8"
        assert nip66_full.geo_country == "US"
        assert nip66_full.geo_region == "California"
        assert nip66_full.geo_city == "Mountain View"
        assert nip66_full.geo_lat == 37.386
        assert nip66_full.geo_lon == -122.084
        assert nip66_full.geo_tz == "America/Los_Angeles"
        assert nip66_full.geohash == "9q9hvu7wp"
        assert nip66_full.geo_asn == 15169
        assert nip66_full.geo_asn_org == "GOOGLE"

    def test_missing_geo_metadata(self, nip66_rtt_only):
        """Missing geo metadata returns None for all geo properties."""
        assert nip66_rtt_only.geo_ip is None
        assert nip66_rtt_only.geo_country is None
        assert nip66_rtt_only.geo_region is None
        assert nip66_rtt_only.geo_city is None
        assert nip66_rtt_only.geo_lat is None
        assert nip66_rtt_only.geo_lon is None
        assert nip66_rtt_only.geo_tz is None
        assert nip66_rtt_only.geohash is None
        assert nip66_rtt_only.geo_asn is None
        assert nip66_rtt_only.geo_asn_org is None

    def test_has_geo(self, nip66_full, nip66_rtt_only):
        """has_geo property."""
        assert nip66_full.has_geo is True
        assert nip66_rtt_only.has_geo is False


class TestMetadataParsing:
    """Test metadata parsing and type validation."""

    def test_filters_invalid_rtt_types(self, relay):
        """Invalid types in RTT metadata are filtered."""
        data = {
            "rtt_open": "fast",  # Invalid: should be int
            "rtt_read": 150,  # Valid
            "rtt_dns": None,  # Invalid: should be int
        }
        nip66 = Nip66(relay=relay, rtt_metadata=Metadata(data))
        assert nip66.rtt_metadata is not None
        assert nip66.rtt_open is None
        assert nip66.rtt_read == 150
        assert nip66.rtt_dns is None

    def test_filters_invalid_ssl_types(self, relay):
        """Invalid types in SSL metadata are filtered."""
        data = {
            "ssl_valid": "yes",  # Invalid: should be bool
            "ssl_issuer": 123,  # Invalid: should be str
            "ssl_expires": 1735689600,  # Valid
        }
        nip66 = Nip66(relay=relay, ssl_metadata=Metadata(data))
        assert nip66.ssl_metadata is not None
        assert nip66.ssl_valid is None
        assert nip66.ssl_issuer is None
        assert nip66.ssl_expires == 1735689600

    def test_filters_invalid_geo_types(self, relay):
        """Invalid types in geo metadata are filtered."""
        data = {
            "geo_ip": 127001,  # Invalid: should be str
            "geo_country": "US",  # Valid
            "geo_lat": "37.386",  # Invalid: should be float
            "geo_lon": -122.084,  # Valid
            "geo_asn": "15169",  # Invalid: should be int
        }
        nip66 = Nip66(relay=relay, geo_metadata=Metadata(data))
        assert nip66.geo_metadata is not None
        assert nip66.geo_ip is None
        assert nip66.geo_country == "US"
        assert nip66.geo_lat is None
        assert nip66.geo_lon == -122.084
        assert nip66.geo_asn is None


class TestToRelayMetadata:
    """Test to_relay_metadata() method."""

    def test_returns_tuple_of_three(self, nip66_full):
        """Returns tuple of three RelayMetadata objects."""
        rtt, ssl, geo = nip66_full.to_relay_metadata()
        assert isinstance(rtt, RelayMetadata)
        assert isinstance(ssl, RelayMetadata)
        assert isinstance(geo, RelayMetadata)

    def test_correct_metadata_types(self, nip66_full):
        """Each RelayMetadata has correct type."""
        rtt, ssl, geo = nip66_full.to_relay_metadata()
        assert rtt.metadata_type == MetadataType.NIP66_RTT
        assert ssl.metadata_type == MetadataType.NIP66_SSL
        assert geo.metadata_type == MetadataType.NIP66_GEO

    def test_returns_none_for_missing(self, nip66_rtt_only):
        """Returns None for missing metadata types."""
        rtt, ssl, geo = nip66_rtt_only.to_relay_metadata()
        assert rtt is not None
        assert rtt.metadata_type == MetadataType.NIP66_RTT
        assert ssl is None
        assert geo is None

    def test_preserves_relay(self, nip66_full):
        """Each RelayMetadata preserves relay reference."""
        rtt, ssl, geo = nip66_full.to_relay_metadata()
        assert rtt.relay is nip66_full.relay
        assert ssl.relay is nip66_full.relay
        assert geo.relay is nip66_full.relay

    def test_preserves_generated_at(self, nip66_full):
        """Each RelayMetadata preserves generated_at timestamp."""
        rtt, ssl, geo = nip66_full.to_relay_metadata()
        assert rtt.generated_at == 1234567890
        assert ssl.generated_at == 1234567890
        assert geo.generated_at == 1234567890


class TestResolveDnsSync:
    """Test _resolve_dns_sync() static method."""

    def test_success(self):
        """Successful DNS resolution returns IP and RTT."""
        with patch("socket.gethostbyname", return_value="8.8.8.8"):
            ip, rtt = Nip66._resolve_dns_sync("example.com")
        assert ip == "8.8.8.8"
        assert isinstance(rtt, int)
        assert rtt >= 0

    def test_failure_raises_gaierror(self):
        """DNS resolution failure raises socket.gaierror."""
        with (
            patch("socket.gethostbyname", side_effect=socket.gaierror("DNS lookup failed")),
            pytest.raises(socket.gaierror),
        ):
            Nip66._resolve_dns_sync("nonexistent.example.com")


class TestCheckSslSync:
    """Test _check_ssl_sync() static method."""

    def test_success_returns_valid_cert(self):
        """Successful SSL check returns ssl_valid=True and cert info."""
        mock_cert = {
            "issuer": ((("organizationName", "Test CA"),),),
            "notAfter": "Jan  1 00:00:00 2025 GMT",
        }

        with patch("socket.create_connection") as mock_conn:
            mock_socket = MagicMock()
            mock_conn.return_value.__enter__.return_value = mock_socket
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)

            with patch("ssl.create_default_context") as mock_ctx:
                mock_ssl_socket = MagicMock()
                mock_ssl_socket.getpeercert.return_value = mock_cert
                mock_wrapped = MagicMock()
                mock_wrapped.__enter__.return_value = mock_ssl_socket
                mock_wrapped.__exit__ = MagicMock(return_value=False)
                mock_ctx.return_value.wrap_socket.return_value = mock_wrapped

                result = Nip66._check_ssl_sync("example.com", 443, 30.0)

        assert result["ssl_valid"] is True
        assert result.get("ssl_issuer") == "Test CA"
        assert "ssl_expires" in result

    def test_ssl_error_raises(self):
        """SSL error raises exception."""
        import ssl as ssl_module

        with patch("socket.create_connection") as mock_conn:
            mock_socket = MagicMock()
            mock_conn.return_value.__enter__.return_value = mock_socket
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)

            with (
                patch("ssl.create_default_context") as mock_ctx,
                pytest.raises(ssl_module.SSLError),
            ):
                mock_ctx.return_value.wrap_socket.side_effect = ssl_module.SSLError()
                Nip66._check_ssl_sync("example.com", 443, 30.0)

    def test_connection_error_raises(self):
        """Connection error raises exception."""
        with (
            patch("socket.create_connection", side_effect=TimeoutError()),
            pytest.raises(TimeoutError),
        ):
            Nip66._check_ssl_sync("example.com", 443, 30.0)


class TestLookupGeoSync:
    """Test _lookup_geo_sync() static method."""

    def test_success_with_city_reader(self):
        """Successful lookup returns geo data."""
        mock_response = MagicMock()
        mock_response.country.iso_code = "US"
        mock_response.city.name = "Mountain View"
        mock_response.location.latitude = 37.386
        mock_response.location.longitude = -122.084
        mock_response.location.time_zone = "America/Los_Angeles"
        mock_response.subdivisions.most_specific.name = "California"

        mock_city_reader = MagicMock()
        mock_city_reader.city.return_value = mock_response

        result = Nip66._lookup_geo_sync("8.8.8.8", mock_city_reader)

        assert result["geo_ip"] == "8.8.8.8"
        assert result["geo_country"] == "US"
        assert result["geo_city"] == "Mountain View"
        assert result["geo_lat"] == 37.386
        assert result["geo_lon"] == -122.084
        assert result["geo_tz"] == "America/Los_Angeles"
        assert result["geo_region"] == "California"
        assert "geohash" in result  # Generated from lat/lon

    def test_success_with_asn_reader(self):
        """Lookup with ASN reader includes ASN data."""
        mock_city_response = MagicMock()
        mock_city_response.country.iso_code = "US"
        mock_city_response.city.name = None
        mock_city_response.location.latitude = 37.0
        mock_city_response.location.longitude = -122.0
        mock_city_response.location.time_zone = None
        mock_city_response.subdivisions = []

        mock_asn_response = MagicMock()
        mock_asn_response.autonomous_system_number = 15169
        mock_asn_response.autonomous_system_organization = "GOOGLE"

        mock_city_reader = MagicMock()
        mock_city_reader.city.return_value = mock_city_response

        mock_asn_reader = MagicMock()
        mock_asn_reader.asn.return_value = mock_asn_response

        result = Nip66._lookup_geo_sync("8.8.8.8", mock_city_reader, mock_asn_reader)

        assert result["geo_asn"] == 15169
        assert result["geo_asn_org"] == "GOOGLE"

    def test_handles_missing_fields(self):
        """Handles missing fields gracefully."""
        mock_response = MagicMock()
        mock_response.country.iso_code = None
        mock_response.city.name = None
        mock_response.location.latitude = None
        mock_response.location.longitude = None
        mock_response.location.time_zone = None
        mock_response.subdivisions = []

        mock_city_reader = MagicMock()
        mock_city_reader.city.return_value = mock_response

        result = Nip66._lookup_geo_sync("8.8.8.8", mock_city_reader)

        assert result["geo_ip"] == "8.8.8.8"
        assert "geo_country" not in result
        assert "geohash" not in result  # No coordinates


class TestTestRtt:
    """Test _test_rtt() class method."""

    @pytest.mark.asyncio
    async def test_returns_metadata_on_success(self, relay):
        """Returns Metadata on successful test."""
        mock_client = AsyncMock()
        mock_client.fetch_events = AsyncMock(return_value=[])
        mock_client.send_event_builder = AsyncMock(return_value=MagicMock())
        mock_client.shutdown = AsyncMock()

        mock_keys = MagicMock()
        mock_keys._inner = MagicMock()
        mock_event_builder = MagicMock()

        with (
            patch("models.nip66.Client", return_value=mock_client),
            patch("models.nip66.NostrSigner"),
            patch.object(Nip66, "_resolve_dns_sync", return_value=("8.8.8.8", 50)),
        ):
            result = await Nip66._test_rtt(relay, 10.0, mock_keys, mock_event_builder)

        assert isinstance(result, Metadata)
        assert "rtt_dns" in result.data
        assert result.data["rtt_dns"] == 50


class TestTestSsl:
    """Test _test_ssl() class method."""

    @pytest.mark.asyncio
    async def test_clearnet_wss_returns_ssl_data(self, relay):
        """Returns SSL data for clearnet wss:// relay."""
        ssl_result = {"ssl_valid": True, "ssl_issuer": "Test CA"}

        with patch.object(Nip66, "_check_ssl_sync", return_value=ssl_result):
            result = await Nip66._test_ssl(relay, 10.0)

        assert isinstance(result, Metadata)
        assert result.data.get("ssl_valid") is True

    @pytest.mark.asyncio
    async def test_ws_returns_empty_metadata(self, ws_relay):
        """Returns empty metadata for ws:// relay (no SSL)."""
        result = await Nip66._test_ssl(ws_relay, 10.0)
        assert isinstance(result, Metadata)
        assert result.data == {}

    @pytest.mark.asyncio
    async def test_tor_returns_empty_metadata(self, tor_relay):
        """Returns empty metadata for Tor relay."""
        result = await Nip66._test_ssl(tor_relay, 10.0)
        assert isinstance(result, Metadata)
        assert result.data == {}


class TestTestGeo:
    """Test _test_geo() class method."""

    @pytest.mark.asyncio
    async def test_clearnet_with_reader_returns_geo_data(self, relay):
        """Returns geo data for clearnet relay with city reader."""
        geo_result = {"geo_ip": "8.8.8.8", "geo_country": "US"}

        mock_city_reader = MagicMock()

        with (
            patch.object(Nip66, "_resolve_dns_sync", return_value=("8.8.8.8", 50)),
            patch.object(Nip66, "_lookup_geo_sync", return_value=geo_result),
        ):
            result = await Nip66._test_geo(relay, mock_city_reader)

        assert isinstance(result, Metadata)
        assert result.data.get("geo_country") == "US"

    @pytest.mark.asyncio
    async def test_tor_returns_empty_metadata(self, tor_relay):
        """Returns empty metadata for Tor relay."""
        mock_city_reader = MagicMock()
        result = await Nip66._test_geo(tor_relay, mock_city_reader)
        assert isinstance(result, Metadata)
        assert result.data == {}

    @pytest.mark.asyncio
    async def test_no_reader_returns_empty_metadata(self, relay):
        """Returns empty metadata when no city reader provided."""
        result = await Nip66._test_geo(relay, city_reader=None)
        assert isinstance(result, Metadata)
        assert result.data == {}

    @pytest.mark.asyncio
    async def test_dns_failure_returns_empty_metadata(self, relay):
        """Returns empty metadata on DNS failure."""
        mock_city_reader = MagicMock()

        with patch.object(Nip66, "_resolve_dns_sync", side_effect=socket.gaierror()):
            result = await Nip66._test_geo(relay, mock_city_reader)

        assert isinstance(result, Metadata)
        assert result.data == {}


class TestTest:
    """Test test() class method."""

    @pytest.mark.asyncio
    async def test_returns_nip66_on_success(self, relay):
        """Returns Nip66 instance on successful test."""
        rtt_data = {"rtt_open": 100, "rtt_read": 150}

        mock_keys = MagicMock()
        mock_keys._inner = MagicMock()
        mock_event_builder = MagicMock()

        with (
            patch.object(
                Nip66, "_test_rtt", new_callable=AsyncMock, return_value=Metadata(rtt_data)
            ),
            patch.object(Nip66, "_test_ssl", new_callable=AsyncMock, return_value=Metadata({})),
            patch.object(Nip66, "_test_geo", new_callable=AsyncMock, return_value=Metadata({})),
        ):
            result = await Nip66.test(relay, keys=mock_keys, event_builder=mock_event_builder)

        assert isinstance(result, Nip66)
        assert result.rtt_open == 100
        assert result.rtt_read == 150

    @pytest.mark.asyncio
    async def test_handles_ssl_failure(self, relay):
        """SSL failure is handled gracefully."""
        rtt_data = {"rtt_open": 100}

        mock_keys = MagicMock()
        mock_keys._inner = MagicMock()
        mock_event_builder = MagicMock()

        with (
            patch.object(
                Nip66, "_test_rtt", new_callable=AsyncMock, return_value=Metadata(rtt_data)
            ),
            patch.object(
                Nip66, "_test_ssl", new_callable=AsyncMock, side_effect=Exception("SSL error")
            ),
            patch.object(Nip66, "_test_geo", new_callable=AsyncMock, return_value=Metadata({})),
        ):
            result = await Nip66.test(relay, keys=mock_keys, event_builder=mock_event_builder)

        assert isinstance(result, Nip66)
        assert result.ssl_metadata is None

    @pytest.mark.asyncio
    async def test_handles_geo_failure(self, relay):
        """Geo failure is handled gracefully."""
        rtt_data = {"rtt_open": 100}

        mock_keys = MagicMock()
        mock_keys._inner = MagicMock()
        mock_event_builder = MagicMock()

        with (
            patch.object(
                Nip66, "_test_rtt", new_callable=AsyncMock, return_value=Metadata(rtt_data)
            ),
            patch.object(Nip66, "_test_ssl", new_callable=AsyncMock, return_value=Metadata({})),
            patch.object(
                Nip66, "_test_geo", new_callable=AsyncMock, side_effect=Exception("Geo error")
            ),
        ):
            result = await Nip66.test(relay, keys=mock_keys, event_builder=mock_event_builder)

        assert isinstance(result, Nip66)
        assert result.geo_metadata is None

    @pytest.mark.asyncio
    async def test_all_tests_fail_raises_error(self, relay):
        """All tests failing raises Nip66TestError."""
        mock_keys = MagicMock()
        mock_keys._inner = MagicMock()
        mock_event_builder = MagicMock()

        with (
            patch.object(Nip66, "_test_rtt", new_callable=AsyncMock, return_value=Metadata({})),
            patch.object(Nip66, "_test_ssl", new_callable=AsyncMock, return_value=Metadata({})),
            patch.object(Nip66, "_test_geo", new_callable=AsyncMock, return_value=Metadata({})),
            pytest.raises(Nip66TestError),
        ):
            await Nip66.test(relay, keys=mock_keys, event_builder=mock_event_builder)

    @pytest.mark.asyncio
    async def test_run_rtt_requires_keys_and_event_builder(self, relay):
        """run_rtt=True requires keys and event_builder."""
        with pytest.raises(ValueError, match="requires keys and event_builder"):
            await Nip66.test(relay, run_rtt=True, keys=None, event_builder=None)

    @pytest.mark.asyncio
    async def test_can_skip_rtt(self, relay):
        """Can skip RTT test with run_rtt=False."""
        ssl_data = {"ssl_valid": True}

        with (
            patch.object(
                Nip66, "_test_ssl", new_callable=AsyncMock, return_value=Metadata(ssl_data)
            ),
            patch.object(Nip66, "_test_geo", new_callable=AsyncMock, return_value=Metadata({})),
        ):
            result = await Nip66.test(relay, run_rtt=False)

        assert isinstance(result, Nip66)
        assert result.rtt_metadata is None
        assert result.ssl_valid is True

    @pytest.mark.asyncio
    async def test_can_skip_ssl(self, relay):
        """Can skip SSL test with run_ssl=False."""
        rtt_data = {"rtt_open": 100}

        mock_keys = MagicMock()
        mock_keys._inner = MagicMock()
        mock_event_builder = MagicMock()

        with (
            patch.object(
                Nip66, "_test_rtt", new_callable=AsyncMock, return_value=Metadata(rtt_data)
            ),
            patch.object(Nip66, "_test_geo", new_callable=AsyncMock, return_value=Metadata({})),
        ):
            result = await Nip66.test(
                relay, keys=mock_keys, event_builder=mock_event_builder, run_ssl=False
            )

        assert isinstance(result, Nip66)
        assert result.ssl_metadata is None

    @pytest.mark.asyncio
    async def test_can_skip_geo(self, relay):
        """Can skip geo test with run_geo=False."""
        rtt_data = {"rtt_open": 100}

        mock_keys = MagicMock()
        mock_keys._inner = MagicMock()
        mock_event_builder = MagicMock()

        with (
            patch.object(
                Nip66, "_test_rtt", new_callable=AsyncMock, return_value=Metadata(rtt_data)
            ),
            patch.object(Nip66, "_test_ssl", new_callable=AsyncMock, return_value=Metadata({})),
        ):
            result = await Nip66.test(
                relay, keys=mock_keys, event_builder=mock_event_builder, run_geo=False
            )

        assert isinstance(result, Nip66)
        assert result.geo_metadata is None


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
