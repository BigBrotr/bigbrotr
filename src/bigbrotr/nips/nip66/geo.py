"""
NIP-66 geolocation metadata container with GeoIP lookup capabilities.

Resolves a relay's hostname to an IP address and performs a GeoIP City
database lookup to determine geographic location, including country,
city, coordinates, and a computed geohash as part of
[NIP-66](https://github.com/nostr-protocol/nips/blob/master/66.md)
monitoring. Clearnet relays only.

Note:
    Hostname resolution uses [resolve_host][bigbrotr.utils.dns.resolve_host],
    preferring IPv4 over IPv6 for the GeoIP lookup. The GeoIP City database
    (GeoLite2-City) must be provided as an open ``geoip2.database.Reader``
    -- the caller is responsible for database lifecycle management.

    The geohash is computed at precision 9 (approximately 5-meter accuracy)
    using the ``geohash2`` library and is useful for spatial proximity
    queries.

See Also:
    [bigbrotr.nips.nip66.data.Nip66GeoData][bigbrotr.nips.nip66.data.Nip66GeoData]:
        Data model for geolocation fields.
    [bigbrotr.nips.nip66.logs.Nip66GeoLogs][bigbrotr.nips.nip66.logs.Nip66GeoLogs]:
        Log model for geolocation lookup results.
    [bigbrotr.nips.nip66.net.Nip66NetMetadata][bigbrotr.nips.nip66.net.Nip66NetMetadata]:
        Network/ASN test that also uses
        [resolve_host][bigbrotr.utils.dns.resolve_host] for IP resolution.
    [bigbrotr.utils.dns.resolve_host][bigbrotr.utils.dns.resolve_host]:
        DNS resolution utility used to obtain IP addresses.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Self

import geohash2
import geoip2.database
import geoip2.errors

from bigbrotr.models.constants import NetworkType
from bigbrotr.models.relay import Relay  # noqa: TC001
from bigbrotr.nips.base import BaseNipMetadata
from bigbrotr.utils.dns import resolve_host

from .data import Nip66GeoData
from .logs import Nip66GeoLogs


logger = logging.getLogger("bigbrotr.nips.nip66")


class GeoExtractor:
    """Extracts structured geolocation fields from a GeoIP2 City response.

    See Also:
        [Nip66GeoMetadata][bigbrotr.nips.nip66.geo.Nip66GeoMetadata]:
            Container that uses this extractor during geolocation lookup.
        [bigbrotr.nips.nip66.data.Nip66GeoData][bigbrotr.nips.nip66.data.Nip66GeoData]:
            Data model populated by the extracted fields.
    """

    @staticmethod
    def extract_country(response: Any) -> dict[str, Any]:
        """Extract country code, name, and EU membership status."""
        result: dict[str, Any] = {}

        # Prefer the physical country; fall back to registered country
        if response.country.iso_code:
            result["geo_country"] = response.country.iso_code
        elif response.registered_country.iso_code:
            result["geo_country"] = response.registered_country.iso_code

        if response.country.name:
            result["geo_country_name"] = response.country.name
        elif response.registered_country.name:
            result["geo_country_name"] = response.registered_country.name

        is_eu = response.country.is_in_european_union
        if is_eu is not None:
            result["geo_is_eu"] = is_eu

        return result

    @staticmethod
    def extract_administrative(response: Any) -> dict[str, Any]:
        """Extract continent, city, region, postal code, and geoname ID."""
        result: dict[str, Any] = {}

        if response.continent.code:
            result["geo_continent"] = response.continent.code
        if response.continent.name:
            result["geo_continent_name"] = response.continent.name

        if response.city.name:
            result["geo_city"] = response.city.name
        if response.city.geoname_id:
            result["geo_geoname_id"] = response.city.geoname_id

        if response.subdivisions:
            region = response.subdivisions.most_specific.name
            if region:
                result["geo_region"] = region

        if response.postal.code:
            result["geo_postal"] = response.postal.code

        return result

    @staticmethod
    def extract_location(response: Any, geohash_precision: int = 9) -> dict[str, Any]:
        """Extract latitude, longitude, accuracy radius, timezone, and geohash."""
        result: dict[str, Any] = {}
        loc = response.location

        if loc.latitude is not None:
            result["geo_lat"] = loc.latitude
        if loc.longitude is not None:
            result["geo_lon"] = loc.longitude
        if loc.accuracy_radius is not None:
            result["geo_accuracy"] = loc.accuracy_radius
        if loc.time_zone:
            result["geo_tz"] = loc.time_zone

        # Compute geohash from coordinates when both are available
        if "geo_lat" in result and "geo_lon" in result:
            result["geo_hash"] = geohash2.encode(
                result["geo_lat"],
                result["geo_lon"],
                precision=geohash_precision,
            )

        return result

    @classmethod
    def extract_all(cls, response: Any, geohash_precision: int = 9) -> dict[str, Any]:
        """Extract all geolocation fields from a GeoIP2 City response."""
        result: dict[str, Any] = {}
        result.update(cls.extract_country(response))
        result.update(cls.extract_administrative(response))
        result.update(cls.extract_location(response, geohash_precision=geohash_precision))
        return result


class Nip66GeoMetadata(BaseNipMetadata):
    """Container for geolocation data and lookup logs.

    Provides the ``execute()`` class method that resolves the relay hostname,
    performs a GeoIP City lookup, and extracts location fields.

    See Also:
        [bigbrotr.nips.nip66.nip66.Nip66][bigbrotr.nips.nip66.nip66.Nip66]:
            Top-level model that orchestrates this alongside other tests.
        [bigbrotr.models.metadata.MetadataType][bigbrotr.models.metadata.MetadataType]:
            The ``NIP66_GEO`` variant used when storing these results.
        [bigbrotr.nips.nip66.net.Nip66NetMetadata][bigbrotr.nips.nip66.net.Nip66NetMetadata]:
            Network/ASN test that shares the IP resolution step.
    """

    data: Nip66GeoData
    logs: Nip66GeoLogs

    # -------------------------------------------------------------------------
    # Geolocation Lookup
    # -------------------------------------------------------------------------

    @staticmethod
    def _geo(
        ip: str, city_reader: geoip2.database.Reader, geohash_precision: int = 9
    ) -> dict[str, Any]:
        """Perform a synchronous GeoIP City database lookup.

        Args:
            ip: Resolved IP address string.
            city_reader: Open GeoLite2-City database reader.
            geohash_precision: Geohash encoding precision (1-12, default 9).

        Returns:
            Dictionary of geolocation fields, or empty dict on error.
        """
        try:
            response = city_reader.city(ip)
            return GeoExtractor.extract_all(response, geohash_precision=geohash_precision)
        except (geoip2.errors.GeoIP2Error, ValueError) as e:
            logger.debug("geo_geoip_lookup_error ip=%s error=%s", ip, str(e))
            return {}

    @classmethod
    async def execute(
        cls,
        relay: Relay,
        city_reader: geoip2.database.Reader,
        geohash_precision: int = 9,
    ) -> Self:
        """Perform a geolocation lookup for a clearnet relay.

        Resolves the relay hostname to an IP (preferring IPv4), then
        queries the GeoIP City database in a thread pool.

        Args:
            relay: Clearnet relay to geolocate.
            city_reader: Open GeoLite2-City database reader.

        Returns:
            An ``Nip66GeoMetadata`` instance with location data and logs.
        """
        logger.debug("geo_testing relay=%s", relay.url)

        if relay.network != NetworkType.CLEARNET:
            return cls(
                data=Nip66GeoData(),
                logs=Nip66GeoLogs(
                    success=False, reason=f"requires clearnet, got {relay.network.value}"
                ),
            )

        logs: dict[str, Any] = {"success": False, "reason": None}

        resolved = await resolve_host(relay.host)
        ip = resolved.ipv4 or resolved.ipv6

        data: dict[str, Any] = {}
        if ip:
            try:
                data = await asyncio.to_thread(cls._geo, ip, city_reader, geohash_precision)
                if data:
                    logs["success"] = True
                    logger.debug(
                        "geo_completed relay=%s country=%s", relay.url, data.get("geo_country")
                    )
                else:
                    logs["reason"] = "no geo data found for IP"
                    logger.debug("geo_no_data relay=%s", relay.url)
            except (geoip2.errors.GeoIP2Error, ValueError) as e:
                logs["reason"] = str(e)
                logger.debug("geo_lookup_failed relay=%s error=%s", relay.url, str(e))
        else:
            logs["reason"] = "could not resolve hostname to IP"
            logger.debug("geo_no_ip relay=%s", relay.url)

        return cls(
            data=Nip66GeoData.model_validate(Nip66GeoData.parse(data)),
            logs=Nip66GeoLogs.model_validate(logs),
        )
