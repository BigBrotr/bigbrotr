"""NIP-66 geo metadata container with lookup capabilities."""

from __future__ import annotations

import asyncio
from typing import Any, Self

import geohash2
import geoip2.database  # noqa: TC002 - used at runtime

from core.logger import Logger
from models.nips.base import BaseMetadata
from models.relay import NetworkType, Relay
from utils.dns import resolve_host

from .data import Nip66GeoData
from .logs import Nip66GeoLogs


logger = Logger("models.nip66")


class Nip66GeoMetadata(BaseMetadata):
    """Container for Geo data and logs with lookup capabilities."""

    data: Nip66GeoData
    logs: Nip66GeoLogs

    # -------------------------------------------------------------------------
    # Geo Lookup
    # -------------------------------------------------------------------------

    @staticmethod
    def _geo(ip: str, city_reader: geoip2.database.Reader) -> dict[str, Any]:
        """Synchronous geolocation lookup."""
        result: dict[str, Any] = {}

        try:
            response = city_reader.city(ip)

            # Country
            if response.country.iso_code:
                result["geo_country"] = response.country.iso_code
            elif response.registered_country.iso_code:
                result["geo_country"] = response.registered_country.iso_code

            if response.country.name:
                result["geo_country_name"] = response.country.name
            elif response.registered_country.name:
                result["geo_country_name"] = response.registered_country.name

            # EU membership
            is_eu = response.country.is_in_european_union
            if is_eu is not None:
                result["geo_is_eu"] = is_eu

            # Continent
            if response.continent.code:
                result["geo_continent"] = response.continent.code
            if response.continent.name:
                result["geo_continent_name"] = response.continent.name

            # City
            if response.city.name:
                result["geo_city"] = response.city.name
            if response.city.geoname_id:
                result["geo_geoname_id"] = response.city.geoname_id

            # Region
            if response.subdivisions:
                region = response.subdivisions.most_specific.name
                if region:
                    result["geo_region"] = region

            # Postal
            if response.postal.code:
                result["geo_postal"] = response.postal.code

            # Location
            if response.location.latitude is not None:
                result["geo_lat"] = response.location.latitude
            if response.location.longitude is not None:
                result["geo_lon"] = response.location.longitude
            if response.location.accuracy_radius is not None:
                result["geo_accuracy"] = response.location.accuracy_radius
            if response.location.time_zone:
                result["geo_tz"] = response.location.time_zone

            # Generate geohash if coordinates available
            if "geo_lat" in result and "geo_lon" in result:
                result["geohash"] = geohash2.encode(
                    result["geo_lat"],
                    result["geo_lon"],
                    precision=9,
                )
        except Exception as e:
            logger.debug("geo_geoip_lookup_error", ip=ip, error=str(e))

        return result

    @classmethod
    async def geo(
        cls,
        relay: Relay,
        city_reader: geoip2.database.Reader,
    ) -> Self:
        """Lookup geolocation for relay.

        Raises:
            ValueError: If non-clearnet relay.
        """
        logger.debug("geo_testing", relay=relay.url)

        if relay.network != NetworkType.CLEARNET:
            raise ValueError(f"geo lookup requires clearnet, got {relay.network.value}")

        logs: dict[str, Any] = {"success": False, "reason": None}

        # Resolve hostname to IP (prefer IPv4 for geo lookup)
        resolved = await resolve_host(relay.host)
        ip = resolved.ipv4 or resolved.ipv6

        data: dict[str, Any] = {}
        if ip:
            try:
                data = await asyncio.to_thread(cls._geo, ip, city_reader)
                if data:
                    logs["success"] = True
                    logger.debug("geo_completed", relay=relay.url, country=data.get("geo_country"))
                else:
                    logs["reason"] = "no geo data found for IP"
                    logger.debug("geo_no_data", relay=relay.url)
            except Exception as e:
                logs["reason"] = str(e)
                logger.debug("geo_lookup_failed", relay=relay.url, error=str(e))
        else:
            logs["reason"] = "could not resolve hostname to IP"
            logger.debug("geo_no_ip", relay=relay.url)

        return cls(
            data=Nip66GeoData.model_validate(Nip66GeoData.parse(data)),
            logs=Nip66GeoLogs.model_validate(logs),
        )
