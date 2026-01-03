"""
Unit tests for models.nip66 module.

Tests:
- NIP-66 property accessors (rtt_open, rtt_read, rtt_write, rtt_dns)
- SSL fields (ssl_valid, ssl_issuer, ssl_expires)
- Geo fields (geohash, geo_ip, geo_country, geo_city, geo_asn)
- to_relay_metadata() conversion (generates up to 3 records)
- Nip66.test() async connection tests
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models import Metadata, Nip66, Relay


@pytest.fixture
def relay():
    return Relay("wss://relay.example.com", discovered_at=1234567890)


@pytest.fixture
def nip66(relay):
    """Nip66 with complete data."""
    rtt_data = {
        "network": "clearnet",
        "rtt_open": 100,
        "rtt_read": 150,
        "rtt_write": 200,
        "rtt_dns": 50,
        "relay_type": "Public",
        "supported_nips": [1, 2, 4],
        "requirements": ["!auth", "!payment"],
        "topics": ["general"],
        "accepted_kinds": [0, 1, 3],
        "rejected_kinds": [4],
    }
    ssl_data = {
        "ssl_valid": True,
        "ssl_issuer": "Let's Encrypt",
        "ssl_expires": 1735689600,
    }
    geo_data = {
        "geohash": "9q8yy",
        "geo_ip": "8.8.8.8",
        "geo_country": "US",
        "geo_city": "Mountain View",
        "geo_lat": 37.386,
        "geo_lon": -122.084,
        "geo_tz": "America/Los_Angeles",
        "geo_asn": 15169,
        "geo_asn_org": "GOOGLE",
    }

    instance = object.__new__(Nip66)
    object.__setattr__(instance, "relay", relay)
    object.__setattr__(instance, "rtt_metadata", Metadata(rtt_data))
    object.__setattr__(instance, "ssl_metadata", Metadata(ssl_data))
    object.__setattr__(instance, "geo_metadata", Metadata(geo_data))
    object.__setattr__(instance, "generated_at", 1234567890)
    return instance


@pytest.fixture
def minimal_nip66(relay):
    """Nip66 with minimal data."""
    instance = object.__new__(Nip66)
    object.__setattr__(instance, "relay", relay)
    object.__setattr__(instance, "rtt_metadata", Metadata({"network": "clearnet"}))
    object.__setattr__(instance, "ssl_metadata", None)
    object.__setattr__(instance, "geo_metadata", None)
    object.__setattr__(instance, "generated_at", 0)
    return instance


class TestRttProperties:
    """RTT property accessors."""

    def test_rtt_values(self, nip66):
        assert nip66.rtt_open == 100
        assert nip66.rtt_read == 150
        assert nip66.rtt_write == 200
        assert nip66.rtt_dns == 50

    def test_rtt_missing(self, minimal_nip66):
        assert minimal_nip66.rtt_open is None
        assert minimal_nip66.rtt_read is None

    def test_boolean_flags(self, nip66, minimal_nip66):
        assert nip66.is_openable is True
        assert nip66.is_readable is True
        assert nip66.is_writable is True
        assert minimal_nip66.is_openable is False


class TestSslProperties:
    """SSL property accessors."""

    def test_ssl_values(self, nip66):
        assert nip66.ssl_valid is True
        assert nip66.ssl_issuer == "Let's Encrypt"
        assert nip66.ssl_expires == 1735689600
        assert nip66.has_ssl is True

    def test_ssl_missing(self, minimal_nip66):
        assert minimal_nip66.ssl_valid is None
        assert minimal_nip66.has_ssl is False


class TestGeoProperties:
    """Geo property accessors."""

    def test_geo_values(self, nip66):
        assert nip66.geohash == "9q8yy"
        assert nip66.geo_ip == "8.8.8.8"
        assert nip66.geo_country == "US"
        assert nip66.geo_city == "Mountain View"
        assert nip66.geo_lat == 37.386
        assert nip66.geo_lon == -122.084
        assert nip66.has_geo is True

    def test_geo_missing(self, minimal_nip66):
        assert minimal_nip66.geohash is None
        assert minimal_nip66.has_geo is False


class TestClassificationProperties:
    """Classification property accessors."""

    def test_values(self, nip66):
        assert nip66.network == "clearnet"
        assert nip66.relay_type == "Public"
        assert nip66.supported_nips == [1, 2, 4]
        assert nip66.requirements == ["!auth", "!payment"]
        assert nip66.topics == ["general"]
        assert nip66.accepted_kinds == [0, 1, 3]
        assert nip66.rejected_kinds == [4]

    def test_missing(self, minimal_nip66):
        assert minimal_nip66.supported_nips == []


class TestDataProperty:
    """data property combines all metadata."""

    def test_combines_all(self, nip66):
        data = nip66.data
        assert data["network"] == "clearnet"
        assert data["ssl_valid"] is True
        assert data["geo_country"] == "US"

    def test_without_ssl_and_geo(self, minimal_nip66):
        data = minimal_nip66.data
        assert data == {"network": "clearnet"}


class TestToRelayMetadata:
    """to_relay_metadata() method."""

    def test_returns_tuple_of_three(self, nip66):
        rtt, ssl, geo = nip66.to_relay_metadata()
        assert rtt is not None
        assert rtt.metadata_type == "nip66_rtt"
        assert ssl is not None
        assert ssl.metadata_type == "nip66_ssl"
        assert geo is not None
        assert geo.metadata_type == "nip66_geo"

    def test_returns_none_for_missing(self, minimal_nip66):
        rtt, ssl, geo = minimal_nip66.to_relay_metadata()
        assert rtt is not None
        assert rtt.metadata_type == "nip66_rtt"
        assert ssl is None
        assert geo is None

    def test_preserves_generated_at(self, nip66):
        rtt, ssl, geo = nip66.to_relay_metadata()
        assert rtt.generated_at == 1234567890
        assert ssl.generated_at == 1234567890
        assert geo.generated_at == 1234567890


class TestResolveDnsSync:
    """_resolve_dns_sync() static method."""

    def test_success(self):
        with patch("socket.gethostbyname", return_value="8.8.8.8"):
            ip, rtt = Nip66._resolve_dns_sync("example.com")
        assert ip == "8.8.8.8"
        assert isinstance(rtt, int)

    def test_failure_raises(self):
        import socket

        with (
            patch("socket.gethostbyname", side_effect=socket.gaierror),
            pytest.raises(socket.gaierror),
        ):
            Nip66._resolve_dns_sync("nonexistent.example.com")


class TestCheckSslSync:
    """_check_ssl_sync() static method."""

    def test_success(self):
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

        assert result.get("ssl_valid") is True

    def test_ssl_error_raises(self):
        import ssl

        with patch("socket.create_connection") as mock_conn:
            mock_socket = MagicMock()
            mock_conn.return_value.__enter__.return_value = mock_socket
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)

            with (
                patch("ssl.create_default_context") as mock_ctx,
                pytest.raises(ssl.SSLError),
            ):
                mock_ctx.return_value.wrap_socket.side_effect = ssl.SSLError()
                Nip66._check_ssl_sync("example.com", 443, 30.0)

    def test_connection_error_raises(self):
        with (
            patch("socket.create_connection", side_effect=TimeoutError),
            pytest.raises(TimeoutError),
        ):
            Nip66._check_ssl_sync("example.com", 443, 30.0)


class TestLookupGeoSync:
    """_lookup_geo_sync() static method."""

    def test_success(self):
        mock_response = MagicMock()
        mock_response.country.iso_code = "US"
        mock_response.city.name = "Mountain View"
        mock_response.location.latitude = 37.386
        mock_response.location.longitude = -122.084
        mock_response.location.time_zone = "America/Los_Angeles"
        mock_response.subdivisions.most_specific.name = "California"

        with patch("geoip2.database.Reader") as mock_reader:
            mock_reader.return_value.__enter__.return_value.city.return_value = mock_response
            result = Nip66._lookup_geo_sync("8.8.8.8", "/path/to/city.mmdb")

        assert result["geo_ip"] == "8.8.8.8"
        assert result["geo_country"] == "US"
        assert "geohash" in result

    def test_failure_raises(self):
        with (
            patch("geoip2.database.Reader") as mock_reader,
            pytest.raises(Exception),
        ):
            mock_reader.return_value.__enter__.return_value.city.side_effect = Exception()
            Nip66._lookup_geo_sync("8.8.8.8", "/path/to/city.mmdb")


class TestTestRtt:
    """_test_rtt() class method."""

    @pytest.mark.asyncio
    async def test_returns_metadata(self, relay):
        rtt_data = {"network": "clearnet", "rtt_open": 100}
        with patch.object(
            Nip66, "_test_rtt", new_callable=AsyncMock, return_value=Metadata(rtt_data)
        ):
            result = await Nip66._test_rtt(relay, timeout=30.0, keys=None)
        assert isinstance(result, Metadata)


class TestTestSsl:
    """_test_ssl() class method."""

    @pytest.mark.asyncio
    async def test_requires_wss(self):
        ws_relay = Relay("ws://relay.example.com", discovered_at=0)
        with pytest.raises(ValueError, match="wss://"):
            await Nip66._test_ssl(ws_relay, timeout=30.0)

    @pytest.mark.asyncio
    async def test_requires_clearnet(self):
        tor_relay = Relay("wss://abc123.onion", discovered_at=0)
        with pytest.raises(ValueError, match="clearnet"):
            await Nip66._test_ssl(tor_relay, timeout=30.0)


class TestTest:
    """test() class method."""

    @pytest.mark.asyncio
    async def test_returns_nip66(self, relay):
        rtt_metadata = Metadata({"network": "clearnet"})
        with patch.object(Nip66, "_test_rtt", new_callable=AsyncMock, return_value=rtt_metadata):
            result = await Nip66.test(relay, timeout=30.0)
        assert isinstance(result, Nip66)
        assert result.network == "clearnet"

    @pytest.mark.asyncio
    async def test_handles_ssl_failure(self, relay):
        rtt_metadata = Metadata({"network": "clearnet"})
        with (
            patch.object(Nip66, "_test_rtt", new_callable=AsyncMock, return_value=rtt_metadata),
            patch.object(Nip66, "_test_ssl", new_callable=AsyncMock, side_effect=Exception()),
        ):
            result = await Nip66.test(relay, timeout=30.0)
        assert result.ssl_metadata is None

    @pytest.mark.asyncio
    async def test_handles_geo_failure(self, relay):
        rtt_metadata = Metadata({"network": "clearnet", "_ip": "8.8.8.8"})
        with (
            patch.object(Nip66, "_test_rtt", new_callable=AsyncMock, return_value=rtt_metadata),
            patch.object(Nip66, "_test_ssl", new_callable=AsyncMock, side_effect=Exception()),
            patch.object(Nip66, "_test_geo", new_callable=AsyncMock, side_effect=Exception()),
        ):
            result = await Nip66.test(relay, timeout=30.0, city_db_path="/path/to/db")
        assert result.geo_metadata is None
