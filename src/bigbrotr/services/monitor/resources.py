"""Monitor-owned runtime resources."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    import geoip2.database


class GeoReaders:
    """GeoIP database reader container for city and ASN lookups."""

    __slots__ = ("asn", "city")

    def __init__(self) -> None:
        self.city: geoip2.database.Reader | None = None
        self.asn: geoip2.database.Reader | None = None

    async def open(
        self,
        *,
        city_path: str | None = None,
        asn_path: str | None = None,
    ) -> None:
        """Open GeoIP readers from file paths via ``asyncio.to_thread``."""
        import geoip2.database as geoip2_db  # noqa: PLC0415

        if city_path:
            self.city = await asyncio.to_thread(geoip2_db.Reader, city_path)
        if asn_path:
            self.asn = await asyncio.to_thread(geoip2_db.Reader, asn_path)

    def close(self) -> None:
        """Close readers and clear cached handles. Safe to call repeatedly."""
        if self.city:
            self.city.close()
            self.city = None
        if self.asn:
            self.asn.close()
            self.asn = None
