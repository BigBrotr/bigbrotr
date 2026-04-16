"""Monitor-owned runtime resources.

These helpers are specific to the monitor service even though they support
cross-cutting concerns like GeoIP readers and relay client reuse.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING


logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    import geoip2.database
    from nostr_sdk import Client, Keys

    from bigbrotr.models import Relay
    from bigbrotr.services.common.configs import NetworksConfig


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


class RelayClients:
    """Lazy pool of relay clients used by monitor publishing flows."""

    __slots__ = ("_manager",)

    def __init__(
        self,
        keys: Keys,
        networks: NetworksConfig,
        *,
        allow_insecure: bool = False,
    ) -> None:
        from bigbrotr.utils.protocol import NostrClientManager  # noqa: PLC0415

        self._manager = NostrClientManager(
            keys=keys,
            networks=networks,
            allow_insecure=allow_insecure,
        )

    async def get(self, relay: Relay) -> Client | None:
        """Return a connected client for a relay, connecting lazily."""
        return await self._manager.get_relay_client(relay)

    async def get_many(self, relays: list[Relay]) -> list[Client]:
        """Return connected clients for multiple relays."""
        return await self._manager.get_relay_clients(relays)

    async def disconnect(self) -> None:
        """Disconnect all clients and reset cached state."""
        await self._manager.disconnect()
