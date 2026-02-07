"""
Unit tests for models.nips.nip66.geo module.

Tests:
- GeoExtractor.extract_country() - country code, name, EU membership
- GeoExtractor.extract_administrative() - continent, city, region, postal
- GeoExtractor.extract_location() - lat, lon, accuracy, tz, geohash
- GeoExtractor.extract_all() - combines all extraction methods
- Nip66GeoMetadata._geo() - synchronous lookup
- Nip66GeoMetadata.geo() - async lookup with clearnet validation
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models import Relay
from models.nips.nip66.geo import GeoExtractor, Nip66GeoMetadata


class TestGeoExtractorExtractCountry:
    """Test GeoExtractor.extract_country() method."""

    def test_extracts_country_code_from_country(self) -> None:
        """Extract country code from primary country field."""
        response = MagicMock()
        response.country.iso_code = "US"
        response.country.name = "United States"
        response.country.is_in_european_union = False
        response.registered_country.iso_code = None
        response.registered_country.name = None

        result = GeoExtractor.extract_country(response)

        assert result["geo_country"] == "US"
        assert result["geo_country_name"] == "United States"
        assert result["geo_is_eu"] is False

    def test_fallback_to_registered_country(self) -> None:
        """Fall back to registered_country when country is None."""
        response = MagicMock()
        response.country.iso_code = None
        response.country.name = None
        response.country.is_in_european_union = None
        response.registered_country.iso_code = "DE"
        response.registered_country.name = "Germany"

        result = GeoExtractor.extract_country(response)

        assert result["geo_country"] == "DE"
        assert result["geo_country_name"] == "Germany"

    def test_eu_membership_true(self) -> None:
        """Extract EU membership when True."""
        response = MagicMock()
        response.country.iso_code = "FR"
        response.country.name = "France"
        response.country.is_in_european_union = True
        response.registered_country.iso_code = None
        response.registered_country.name = None

        result = GeoExtractor.extract_country(response)

        assert result["geo_is_eu"] is True

    def test_eu_membership_none_not_included(self) -> None:
        """EU membership not included when None."""
        response = MagicMock()
        response.country.iso_code = "US"
        response.country.name = "United States"
        response.country.is_in_european_union = None
        response.registered_country.iso_code = None
        response.registered_country.name = None

        result = GeoExtractor.extract_country(response)

        assert "geo_is_eu" not in result

    def test_empty_response_returns_empty_dict(self) -> None:
        """Empty country data returns empty dict."""
        response = MagicMock()
        response.country.iso_code = None
        response.country.name = None
        response.country.is_in_european_union = None
        response.registered_country.iso_code = None
        response.registered_country.name = None

        result = GeoExtractor.extract_country(response)

        assert result == {}


class TestGeoExtractorExtractAdministrative:
    """Test GeoExtractor.extract_administrative() method."""

    def test_extracts_continent(self) -> None:
        """Extract continent code and name."""
        response = MagicMock()
        response.continent.code = "NA"
        response.continent.name = "North America"
        response.city.name = None
        response.city.geoname_id = None
        response.postal.code = None
        response.subdivisions = []

        result = GeoExtractor.extract_administrative(response)

        assert result["geo_continent"] == "NA"
        assert result["geo_continent_name"] == "North America"

    def test_extracts_city(self) -> None:
        """Extract city name and geoname ID."""
        response = MagicMock()
        response.continent.code = None
        response.continent.name = None
        response.city.name = "Mountain View"
        response.city.geoname_id = 5375480
        response.postal.code = None
        response.subdivisions = []

        result = GeoExtractor.extract_administrative(response)

        assert result["geo_city"] == "Mountain View"
        assert result["geo_geoname_id"] == 5375480

    def test_extracts_region_from_subdivisions(self) -> None:
        """Extract region from subdivisions.most_specific."""
        response = MagicMock()
        response.continent.code = None
        response.continent.name = None
        response.city.name = None
        response.city.geoname_id = None
        response.postal.code = None
        # Subdivisions must be truthy to trigger region extraction
        mock_subdivisions = MagicMock()
        mock_subdivisions.__bool__ = MagicMock(return_value=True)
        mock_subdivisions.most_specific.name = "California"
        response.subdivisions = mock_subdivisions

        result = GeoExtractor.extract_administrative(response)

        assert result["geo_region"] == "California"

    def test_extracts_postal_code(self) -> None:
        """Extract postal code."""
        response = MagicMock()
        response.continent.code = None
        response.continent.name = None
        response.city.name = None
        response.city.geoname_id = None
        response.postal.code = "94035"
        response.subdivisions = []

        result = GeoExtractor.extract_administrative(response)

        assert result["geo_postal"] == "94035"

    def test_empty_subdivisions_no_region(self) -> None:
        """No region when subdivisions is empty."""
        response = MagicMock()
        response.continent.code = None
        response.continent.name = None
        response.city.name = None
        response.city.geoname_id = None
        response.postal.code = None
        response.subdivisions = []

        result = GeoExtractor.extract_administrative(response)

        assert "geo_region" not in result

    def test_complete_administrative_data(self) -> None:
        """Extract all administrative fields at once."""
        response = MagicMock()
        response.continent.code = "EU"
        response.continent.name = "Europe"
        response.city.name = "Berlin"
        response.city.geoname_id = 2950159
        response.postal.code = "10115"
        mock_subdivisions = MagicMock()
        mock_subdivisions.__bool__ = MagicMock(return_value=True)
        mock_subdivisions.most_specific.name = "Berlin"
        response.subdivisions = mock_subdivisions

        result = GeoExtractor.extract_administrative(response)

        assert result["geo_continent"] == "EU"
        assert result["geo_continent_name"] == "Europe"
        assert result["geo_city"] == "Berlin"
        assert result["geo_geoname_id"] == 2950159
        assert result["geo_postal"] == "10115"
        assert result["geo_region"] == "Berlin"


class TestGeoExtractorExtractLocation:
    """Test GeoExtractor.extract_location() method."""

    def test_extracts_coordinates(self) -> None:
        """Extract latitude and longitude."""
        response = MagicMock()
        response.location.latitude = 37.386
        response.location.longitude = -122.084
        response.location.accuracy_radius = None
        response.location.time_zone = None

        result = GeoExtractor.extract_location(response)

        assert result["geo_lat"] == 37.386
        assert result["geo_lon"] == -122.084

    def test_extracts_accuracy_radius(self) -> None:
        """Extract accuracy radius."""
        response = MagicMock()
        response.location.latitude = 37.386
        response.location.longitude = -122.084
        response.location.accuracy_radius = 10
        response.location.time_zone = None

        result = GeoExtractor.extract_location(response)

        assert result["geo_accuracy"] == 10

    def test_extracts_timezone(self) -> None:
        """Extract timezone."""
        response = MagicMock()
        response.location.latitude = 37.386
        response.location.longitude = -122.084
        response.location.accuracy_radius = None
        response.location.time_zone = "America/Los_Angeles"

        result = GeoExtractor.extract_location(response)

        assert result["geo_tz"] == "America/Los_Angeles"

    def test_generates_geohash_when_coordinates_present(self) -> None:
        """Generate geohash when both lat and lon are present."""
        response = MagicMock()
        response.location.latitude = 37.386
        response.location.longitude = -122.084
        response.location.accuracy_radius = None
        response.location.time_zone = None

        result = GeoExtractor.extract_location(response)

        assert "geohash" in result
        assert isinstance(result["geohash"], str)
        assert len(result["geohash"]) == 9  # Precision 9

    def test_no_geohash_without_latitude(self) -> None:
        """No geohash when latitude is missing."""
        response = MagicMock()
        response.location.latitude = None
        response.location.longitude = -122.084
        response.location.accuracy_radius = None
        response.location.time_zone = None

        result = GeoExtractor.extract_location(response)

        assert "geohash" not in result

    def test_no_geohash_without_longitude(self) -> None:
        """No geohash when longitude is missing."""
        response = MagicMock()
        response.location.latitude = 37.386
        response.location.longitude = None
        response.location.accuracy_radius = None
        response.location.time_zone = None

        result = GeoExtractor.extract_location(response)

        assert "geohash" not in result

    def test_empty_location_returns_empty_dict(self) -> None:
        """Empty location data returns empty dict."""
        response = MagicMock()
        response.location.latitude = None
        response.location.longitude = None
        response.location.accuracy_radius = None
        response.location.time_zone = None

        result = GeoExtractor.extract_location(response)

        assert result == {}

    def test_geohash_precision(self) -> None:
        """Geohash has precision of 9 characters."""
        response = MagicMock()
        response.location.latitude = 0.0
        response.location.longitude = 0.0
        response.location.accuracy_radius = None
        response.location.time_zone = None

        result = GeoExtractor.extract_location(response)

        assert len(result["geohash"]) == 9


class TestGeoExtractorExtractAll:
    """Test GeoExtractor.extract_all() method."""

    def test_combines_all_extraction_methods(
        self,
        mock_geoip_response: MagicMock,
    ) -> None:
        """extract_all combines country, administrative, and location data."""
        result = GeoExtractor.extract_all(mock_geoip_response)

        # From extract_country
        assert result["geo_country"] == "US"
        assert result["geo_country_name"] == "United States"
        assert result["geo_is_eu"] is False

        # From extract_administrative
        assert result["geo_continent"] == "NA"
        assert result["geo_continent_name"] == "North America"
        assert result["geo_city"] == "Mountain View"
        assert result["geo_region"] == "California"
        assert result["geo_postal"] == "94035"
        assert result["geo_geoname_id"] == 5375480

        # From extract_location
        assert result["geo_lat"] == 37.386
        assert result["geo_lon"] == -122.084
        assert result["geo_accuracy"] == 10
        assert result["geo_tz"] == "America/Los_Angeles"
        assert "geohash" in result

    def test_empty_response_returns_empty_dict(self) -> None:
        """Empty response returns empty dict."""
        response = MagicMock()
        response.country.iso_code = None
        response.country.name = None
        response.country.is_in_european_union = None
        response.registered_country.iso_code = None
        response.registered_country.name = None
        response.continent.code = None
        response.continent.name = None
        response.city.name = None
        response.city.geoname_id = None
        response.postal.code = None
        response.subdivisions = []
        response.location.latitude = None
        response.location.longitude = None
        response.location.accuracy_radius = None
        response.location.time_zone = None

        result = GeoExtractor.extract_all(response)

        assert result == {}


class TestNip66GeoMetadataGeoSync:
    """Test Nip66GeoMetadata._geo() synchronous method."""

    def test_successful_lookup(self, mock_geoip_response: MagicMock) -> None:
        """Successful geo lookup returns extracted data."""
        mock_city_reader = MagicMock()
        mock_city_reader.city.return_value = mock_geoip_response

        result = Nip66GeoMetadata._geo("8.8.8.8", mock_city_reader)

        assert result["geo_country"] == "US"
        assert result["geo_city"] == "Mountain View"
        mock_city_reader.city.assert_called_once_with("8.8.8.8")

    def test_lookup_exception_returns_empty_dict(self) -> None:
        """Lookup exception returns empty dict."""
        mock_city_reader = MagicMock()
        mock_city_reader.city.side_effect = Exception("IP not found")

        result = Nip66GeoMetadata._geo("192.168.1.1", mock_city_reader)

        assert result == {}

    def test_lookup_with_different_ip(self, mock_geoip_response: MagicMock) -> None:
        """Lookup with IPv6 address."""
        mock_city_reader = MagicMock()
        mock_city_reader.city.return_value = mock_geoip_response

        result = Nip66GeoMetadata._geo("2001:4860:4860::8888", mock_city_reader)

        assert result["geo_country"] == "US"
        mock_city_reader.city.assert_called_once_with("2001:4860:4860::8888")


class TestNip66GeoMetadataGeoAsync:
    """Test Nip66GeoMetadata.geo() async class method."""

    @pytest.mark.asyncio
    async def test_clearnet_with_reader_returns_geo_metadata(
        self,
        relay: Relay,
        mock_geoip_response: MagicMock,
    ) -> None:
        """Returns Nip66GeoMetadata for clearnet relay with city reader."""
        mock_city_reader = MagicMock()

        mock_resolved = MagicMock()
        mock_resolved.ipv4 = "8.8.8.8"
        mock_resolved.ipv6 = None

        geo_result = {
            "geo_country": "US",
            "geo_country_name": "United States",
            "geo_city": "Mountain View",
        }

        with (
            patch(
                "models.nips.nip66.geo.resolve_host",
                new_callable=AsyncMock,
                return_value=mock_resolved,
            ),
            patch.object(Nip66GeoMetadata, "_geo", return_value=geo_result),
        ):
            result = await Nip66GeoMetadata.geo(relay, mock_city_reader)

        assert isinstance(result, Nip66GeoMetadata)
        assert result.data.geo_country == "US"
        assert result.data.geo_city == "Mountain View"
        assert result.logs.success is True

    @pytest.mark.asyncio
    async def test_tor_raises_value_error(
        self,
        tor_relay: Relay,
        mock_city_reader: MagicMock,
    ) -> None:
        """Raises ValueError for Tor relay (geo not applicable)."""
        with pytest.raises(ValueError, match="geo lookup requires clearnet"):
            await Nip66GeoMetadata.geo(tor_relay, mock_city_reader)

    @pytest.mark.asyncio
    async def test_i2p_raises_value_error(
        self,
        i2p_relay: Relay,
        mock_city_reader: MagicMock,
    ) -> None:
        """Raises ValueError for I2P relay (geo not applicable)."""
        with pytest.raises(ValueError, match="geo lookup requires clearnet"):
            await Nip66GeoMetadata.geo(i2p_relay, mock_city_reader)

    @pytest.mark.asyncio
    async def test_loki_raises_value_error(
        self,
        loki_relay: Relay,
        mock_city_reader: MagicMock,
    ) -> None:
        """Raises ValueError for Lokinet relay (geo not applicable)."""
        with pytest.raises(ValueError, match="geo lookup requires clearnet"):
            await Nip66GeoMetadata.geo(loki_relay, mock_city_reader)

    @pytest.mark.asyncio
    async def test_no_ip_resolved_returns_failure(
        self,
        relay: Relay,
        mock_city_reader: MagicMock,
    ) -> None:
        """Returns failure logs when hostname cannot be resolved to IP."""
        mock_resolved = MagicMock()
        mock_resolved.ipv4 = None
        mock_resolved.ipv6 = None

        with patch(
            "models.nips.nip66.geo.resolve_host", new_callable=AsyncMock, return_value=mock_resolved
        ):
            result = await Nip66GeoMetadata.geo(relay, mock_city_reader)

        assert isinstance(result, Nip66GeoMetadata)
        assert result.logs.success is False
        assert "could not resolve hostname" in result.logs.reason

    @pytest.mark.asyncio
    async def test_no_geo_data_returns_failure(
        self,
        relay: Relay,
        mock_city_reader: MagicMock,
    ) -> None:
        """Returns failure logs when no geo data found for IP."""
        mock_resolved = MagicMock()
        mock_resolved.ipv4 = "8.8.8.8"
        mock_resolved.ipv6 = None

        with (
            patch(
                "models.nips.nip66.geo.resolve_host",
                new_callable=AsyncMock,
                return_value=mock_resolved,
            ),
            patch.object(Nip66GeoMetadata, "_geo", return_value={}),
        ):
            result = await Nip66GeoMetadata.geo(relay, mock_city_reader)

        assert isinstance(result, Nip66GeoMetadata)
        assert result.logs.success is False
        assert "no geo data found" in result.logs.reason

    @pytest.mark.asyncio
    async def test_lookup_exception_returns_failure(
        self,
        relay: Relay,
        mock_city_reader: MagicMock,
    ) -> None:
        """Returns failure logs when lookup raises exception."""
        mock_resolved = MagicMock()
        mock_resolved.ipv4 = "8.8.8.8"
        mock_resolved.ipv6 = None

        with (
            patch(
                "models.nips.nip66.geo.resolve_host",
                new_callable=AsyncMock,
                return_value=mock_resolved,
            ),
            patch.object(Nip66GeoMetadata, "_geo", side_effect=Exception("Database error")),
        ):
            result = await Nip66GeoMetadata.geo(relay, mock_city_reader)

        assert isinstance(result, Nip66GeoMetadata)
        assert result.logs.success is False
        assert "Database error" in result.logs.reason

    @pytest.mark.asyncio
    async def test_prefers_ipv4_for_lookup(
        self,
        relay: Relay,
        mock_city_reader: MagicMock,
    ) -> None:
        """Prefers IPv4 over IPv6 for geo lookup."""
        mock_resolved = MagicMock()
        mock_resolved.ipv4 = "8.8.8.8"
        mock_resolved.ipv6 = "2001:4860:4860::8888"

        geo_result = {"geo_country": "US"}

        with (
            patch(
                "models.nips.nip66.geo.resolve_host",
                new_callable=AsyncMock,
                return_value=mock_resolved,
            ),
            patch.object(Nip66GeoMetadata, "_geo", return_value=geo_result) as mock_geo,
        ):
            await Nip66GeoMetadata.geo(relay, mock_city_reader)

        mock_geo.assert_called_once_with("8.8.8.8", mock_city_reader, 9)

    @pytest.mark.asyncio
    async def test_falls_back_to_ipv6(
        self,
        relay: Relay,
        mock_city_reader: MagicMock,
    ) -> None:
        """Falls back to IPv6 when IPv4 is not available."""
        mock_resolved = MagicMock()
        mock_resolved.ipv4 = None
        mock_resolved.ipv6 = "2001:4860:4860::8888"

        geo_result = {"geo_country": "US"}

        with (
            patch(
                "models.nips.nip66.geo.resolve_host",
                new_callable=AsyncMock,
                return_value=mock_resolved,
            ),
            patch.object(Nip66GeoMetadata, "_geo", return_value=geo_result) as mock_geo,
        ):
            await Nip66GeoMetadata.geo(relay, mock_city_reader)

        mock_geo.assert_called_once_with("2001:4860:4860::8888", mock_city_reader, 9)
