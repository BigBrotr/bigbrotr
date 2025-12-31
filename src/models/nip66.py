"""
NIP-66 types for BigBrotr.

Provides Nip66 class for relay monitoring and discovery.
Nip66 is a factory that generates up to 3 RelayMetadata objects (rtt, ssl, geo).
"""

import asyncio
import socket
import ssl
from dataclasses import dataclass
from datetime import timedelta
from time import perf_counter, time
from typing import TYPE_CHECKING, Any, Optional, TypeVar

import geohash2
import geoip2.database
from nostr_sdk import Client, EventBuilder, Filter, Kind, NostrSigner, RelayUrl

from .keys import Keys
from .metadata import Metadata
from .relay import Relay

if TYPE_CHECKING:
    from .relay_metadata import RelayMetadata


T = TypeVar("T")


@dataclass(frozen=True)
class Nip66:
    """
    Immutable NIP-66 relay monitoring data.

    Collects and stores relay test results, providing type-safe property access
    and conversion to RelayMetadata objects for database storage.

    Generates up to 3 RelayMetadata records:
    - nip66_rtt: Round-trip times and network classification (always present)
    - nip66_ssl: SSL/TLS certificate data (if available)
    - nip66_geo: Geolocation data (if available)
    """

    relay: Relay
    rtt_metadata: Metadata  # RTT and network data (always present)
    ssl_metadata: Optional[Metadata]  # SSL/TLS data (optional)
    geo_metadata: Optional[Metadata]  # Geo data (optional)
    generated_at: int

    # --- Type-safe helpers ---

    def _get_rtt(self, key: str, expected_type: type[T], default: T) -> T:
        """Get value from rtt_metadata with type checking."""
        return self.rtt_metadata._get(key, expected_type, default)

    def _get_rtt_optional(self, key: str, expected_type: type[T]) -> Optional[T]:
        """Get optional value from rtt_metadata with type checking."""
        return self.rtt_metadata._get_optional(key, expected_type)

    def _get_ssl(self, key: str, expected_type: type[T]) -> Optional[T]:
        """Get value from ssl_metadata if available."""
        if self.ssl_metadata is None:
            return None
        return self.ssl_metadata._get_optional(key, expected_type)

    def _get_geo(self, key: str, expected_type: type[T]) -> Optional[T]:
        """Get value from geo_metadata if available."""
        if self.geo_metadata is None:
            return None
        return self.geo_metadata._get_optional(key, expected_type)

    # --- Convenience properties ---

    @property
    def data(self) -> dict[str, Any]:
        """Combined RTT + SSL + geo data for backwards compatibility."""
        result = dict(self.rtt_metadata.data)
        if self.ssl_metadata:
            result.update(self.ssl_metadata.data)
        if self.geo_metadata:
            result.update(self.geo_metadata.data)
        return result

    # --- RTT (Round-Trip Time) ---

    @property
    def rtt_open(self) -> Optional[int]:
        return self._get_rtt_optional("rtt_open", int)

    @property
    def rtt_read(self) -> Optional[int]:
        return self._get_rtt_optional("rtt_read", int)

    @property
    def rtt_write(self) -> Optional[int]:
        return self._get_rtt_optional("rtt_write", int)

    @property
    def rtt_dns(self) -> Optional[int]:
        return self._get_rtt_optional("rtt_dns", int)

    @property
    def is_openable(self) -> bool:
        return self.rtt_open is not None

    @property
    def is_readable(self) -> bool:
        return self.rtt_read is not None

    @property
    def is_writable(self) -> bool:
        return self.rtt_write is not None

    # --- SSL/TLS ---

    @property
    def ssl_valid(self) -> Optional[bool]:
        return self._get_ssl("ssl_valid", bool)

    @property
    def ssl_issuer(self) -> Optional[str]:
        return self._get_ssl("ssl_issuer", str)

    @property
    def ssl_expires(self) -> Optional[int]:
        return self._get_ssl("ssl_expires", int)

    @property
    def has_ssl(self) -> bool:
        """Return True if SSL metadata is present."""
        return self.ssl_metadata is not None

    # --- Classification (in RTT metadata) ---

    @property
    def network(self) -> Optional[str]:
        return self._get_rtt_optional("network", str)

    @property
    def relay_type(self) -> Optional[str]:
        return self._get_rtt_optional("relay_type", str)

    @property
    def supported_nips(self) -> list[int]:
        return self._get_rtt("supported_nips", list, [])

    @property
    def requirements(self) -> list[str]:
        return self._get_rtt("requirements", list, [])

    @property
    def topics(self) -> list[str]:
        return self._get_rtt("topics", list, [])

    @property
    def accepted_kinds(self) -> list[int]:
        return self._get_rtt("accepted_kinds", list, [])

    @property
    def rejected_kinds(self) -> list[int]:
        return self._get_rtt("rejected_kinds", list, [])

    # --- Geolocation ---

    @property
    def geohash(self) -> Optional[str]:
        return self._get_geo("geohash", str)

    @property
    def geo_ip(self) -> Optional[str]:
        return self._get_geo("geo_ip", str)

    @property
    def geo_country(self) -> Optional[str]:
        return self._get_geo("geo_country", str)

    @property
    def geo_region(self) -> Optional[str]:
        return self._get_geo("geo_region", str)

    @property
    def geo_city(self) -> Optional[str]:
        return self._get_geo("geo_city", str)

    @property
    def geo_lat(self) -> Optional[float]:
        return self._get_geo("geo_lat", float)

    @property
    def geo_lon(self) -> Optional[float]:
        return self._get_geo("geo_lon", float)

    @property
    def geo_tz(self) -> Optional[str]:
        return self._get_geo("geo_tz", str)

    @property
    def geo_asn(self) -> Optional[int]:
        return self._get_geo("geo_asn", int)

    @property
    def geo_asn_org(self) -> Optional[str]:
        return self._get_geo("geo_asn_org", str)

    @property
    def geo_isp(self) -> Optional[str]:
        return self._get_geo("geo_isp", str)

    @property
    def has_geo(self) -> bool:
        """Return True if geo metadata is present."""
        return self.geo_metadata is not None

    # --- Internal test methods ---

    @staticmethod
    def _resolve_dns_sync(host: str) -> tuple[Optional[str], Optional[int]]:
        """Synchronous DNS resolution (called via asyncio.to_thread)."""
        try:
            start = perf_counter()
            ip = socket.gethostbyname(host)
            rtt = int((perf_counter() - start) * 1000)
            return ip, rtt
        except socket.gaierror:
            return None, None

    @staticmethod
    async def _resolve_dns(host: str) -> tuple[Optional[str], Optional[int]]:
        """Resolve DNS asynchronously and return (IP, RTT in ms)."""
        return await asyncio.to_thread(Nip66._resolve_dns_sync, host)

    @staticmethod
    def _check_ssl_sync(host: str, port: int = 443) -> dict[str, Any]:
        """Synchronous SSL check (called via asyncio.to_thread)."""
        result: dict[str, Any] = {}
        try:
            context = ssl.create_default_context()
            with (
                socket.create_connection((host, port), timeout=10) as sock,
                context.wrap_socket(sock, server_hostname=host) as ssock,
            ):
                cert = ssock.getpeercert()

                if cert:
                    for rdn in cert.get("issuer", []):
                        for attr, value in rdn:  # type: ignore[misc]
                            if attr == "organizationName":
                                result["ssl_issuer"] = value
                                break

                    not_after = cert.get("notAfter")
                    if not_after and isinstance(not_after, str):
                        # SSL cert expiry is a Unix timestamp
                        result["ssl_expires"] = ssl.cert_time_to_seconds(not_after)

                result["ssl_valid"] = True
        except ssl.SSLError:
            result["ssl_valid"] = False
        except Exception:
            pass

        return result

    @staticmethod
    async def _check_ssl(host: str, port: int = 443) -> dict[str, Any]:
        """Check SSL certificate asynchronously and return ssl_* fields."""
        return await asyncio.to_thread(Nip66._check_ssl_sync, host, port)

    @staticmethod
    def _lookup_geo_sync(
        ip: str,
        city_db_path: str,
        asn_db_path: Optional[str] = None,
    ) -> dict[str, Any]:
        """Synchronous geolocation lookup (called via asyncio.to_thread)."""
        result: dict[str, Any] = {"geo_ip": ip}

        try:
            with geoip2.database.Reader(city_db_path) as reader:
                response = reader.city(ip)

                result["geo_country"] = response.country.iso_code
                result["geo_city"] = response.city.name
                result["geo_lat"] = response.location.latitude
                result["geo_lon"] = response.location.longitude
                result["geo_tz"] = response.location.time_zone

                if response.subdivisions:
                    result["geo_region"] = response.subdivisions.most_specific.name

                if result.get("geo_lat") and result.get("geo_lon"):
                    result["geohash"] = geohash2.encode(
                        result["geo_lat"],
                        result["geo_lon"],
                        precision=9,
                    )
        except Exception:
            pass

        if asn_db_path:
            try:
                with geoip2.database.Reader(asn_db_path) as reader:
                    asn_response = reader.asn(ip)
                    result["geo_asn"] = asn_response.autonomous_system_number
                    result["geo_asn_org"] = asn_response.autonomous_system_organization
            except Exception:
                pass

        return result

    @staticmethod
    async def _lookup_geo(
        ip: str,
        city_db_path: str,
        asn_db_path: Optional[str] = None,
    ) -> dict[str, Any]:
        """Lookup geolocation asynchronously from IP address."""
        return await asyncio.to_thread(
            Nip66._lookup_geo_sync, ip, city_db_path, asn_db_path
        )

    @staticmethod
    async def _test_connection(
        relay: Relay,
        timeout: float,
        keys: Optional[Keys],
    ) -> dict[str, Any]:
        """Test relay connection and return rtt_* fields."""
        result: dict[str, Any] = {}

        # Create client (with or without signer)
        if keys:
            signer = NostrSigner.keys(keys)
            client = Client(signer)
        else:
            client = Client()

        try:
            # Test open
            start = perf_counter()
            relay_url = RelayUrl.parse(relay.url)
            await client.add_relay(relay_url)
            await client.connect()
            result["rtt_open"] = int((perf_counter() - start) * 1000)

            # Test read
            try:
                start = perf_counter()
                f = Filter().limit(1)
                await client.fetch_events([f], timedelta(seconds=timeout))
                result["rtt_read"] = int((perf_counter() - start) * 1000)
            except Exception:
                pass

            # Test write (only if keys provided)
            # Use ephemeral kind (20000-29999) to avoid polluting relay with permanent events
            if keys:
                try:
                    start = perf_counter()
                    builder = EventBuilder(Kind(20000), "")
                    output = await client.send_event_builder(builder)
                    if output:
                        result["rtt_write"] = int((perf_counter() - start) * 1000)
                except Exception:
                    pass

        except Exception:
            pass
        finally:
            # Always shutdown client to release all resources
            try:
                await client.shutdown()
            except Exception:
                pass

        return result

    # --- Factory method ---

    def to_relay_metadata(self) -> list["RelayMetadata"]:
        """
        Convert to RelayMetadata objects for database storage.

        Returns:
            List of RelayMetadata (up to 3):
            - Always includes nip66_rtt (RTT and network data)
            - Includes nip66_ssl if SSL data was collected
            - Includes nip66_geo if geo data was collected
        """
        from .relay_metadata import RelayMetadata

        results = []

        # Always add RTT metadata
        results.append(
            RelayMetadata(
                relay=self.relay,
                metadata=self.rtt_metadata,
                metadata_type="nip66_rtt",
                generated_at=self.generated_at,
            )
        )

        # Add SSL metadata if available
        if self.ssl_metadata is not None:
            results.append(
                RelayMetadata(
                    relay=self.relay,
                    metadata=self.ssl_metadata,
                    metadata_type="nip66_ssl",
                    generated_at=self.generated_at,
                )
            )

        # Add geo metadata if available
        if self.geo_metadata is not None:
            results.append(
                RelayMetadata(
                    relay=self.relay,
                    metadata=self.geo_metadata,
                    metadata_type="nip66_geo",
                    generated_at=self.generated_at,
                )
            )

        return results

    # --- Test ---

    @classmethod
    async def test(
        cls,
        relay: Relay,
        timeout: float = 30.0,
        keys: Optional[Keys] = None,
        city_db_path: Optional[str] = None,
        asn_db_path: Optional[str] = None,
    ) -> "Nip66":
        """
        Test relay and collect NIP-66 monitoring data.

        Args:
            relay: Relay object to test
            timeout: Connection timeout in seconds
            keys: Optional Keys for write test
            city_db_path: Path to GeoLite2-City database
            asn_db_path: Optional path to GeoLite2-ASN database

        Returns:
            Nip66 instance with test results
        """
        rtt_data: dict[str, Any] = {"network": relay.network}
        ssl_data: Optional[dict[str, Any]] = None
        geo_data: Optional[dict[str, Any]] = None
        ip: Optional[str] = None

        # Only perform DNS/SSL/Geo tests for clearnet relays
        # Tor/I2P relays don't resolve via standard DNS
        if relay.network == "clearnet":
            ip, rtt_dns = await cls._resolve_dns(relay.host)
            if rtt_dns is not None:
                rtt_data["rtt_dns"] = rtt_dns

            if relay.scheme == "wss":
                port = relay.port or 443
                ssl_data = await cls._check_ssl(relay.host, port)
                # Only keep ssl_data if it has content
                if not ssl_data:
                    ssl_data = None

            if ip and city_db_path:
                geo_data = await cls._lookup_geo(ip, city_db_path, asn_db_path)

        conn_data = await cls._test_connection(relay, timeout, keys)
        rtt_data.update(conn_data)

        rtt_metadata = Metadata(rtt_data)
        ssl_metadata = Metadata(ssl_data) if ssl_data else None
        geo_metadata = Metadata(geo_data) if geo_data else None
        generated_at = int(time())

        instance = object.__new__(cls)
        object.__setattr__(instance, "relay", relay)
        object.__setattr__(instance, "rtt_metadata", rtt_metadata)
        object.__setattr__(instance, "ssl_metadata", ssl_metadata)
        object.__setattr__(instance, "geo_metadata", geo_metadata)
        object.__setattr__(instance, "generated_at", generated_at)
        return instance
