"""
NIP-66 Relay Monitoring and Discovery model for BigBrotr.

Provides the Nip66 class for testing relay capabilities and collecting monitoring
data per NIP-66 specification. Generates up to 3 RelayMetadata objects for
content-addressed database storage:
- nip66_rtt: Round-trip times and network classification
- nip66_ssl: SSL/TLS certificate information
- nip66_geo: Geolocation data from IP address

See: https://github.com/nostr-protocol/nips/blob/master/66.md

Example:
    >>> nip66 = await Nip66.fetch(relay, keys=keys, geo_reader=geo_db)
    >>> if nip66:
    ...     print(f"Open: {nip66.is_open}, RTT: {nip66.rtt_open}ms")
    ...     print(f"Country: {nip66.country_code}")
"""

import asyncio
import socket
import ssl
from dataclasses import dataclass
from datetime import timedelta
from time import perf_counter, time
from typing import TYPE_CHECKING, Any, ClassVar

import geohash2
import geoip2.database
from nostr_sdk import Client, EventBuilder, Filter, Kind, NostrSigner, RelayUrl

from .keys import Keys
from .metadata import Metadata
from .relay import PORT_WSS, Relay


if TYPE_CHECKING:
    from .relay_metadata import RelayMetadata


@dataclass(frozen=True, slots=True)
class Nip66:
    """
    Immutable NIP-66 relay monitoring data.

    Tests relay capabilities (openable, readable, writable) and collects monitoring
    metrics including round-trip times, SSL certificate data, and geolocation info.
    Provides type-safe property access and conversion to RelayMetadata objects.

    Attributes:
        relay: The Relay being monitored.
        rtt_metadata: RTT and capability data (always present).
        ssl_metadata: SSL/TLS certificate data (optional, clearnet only).
        geo_metadata: Geolocation data (optional, requires GeoIP database).
        generated_at: Unix timestamp when monitoring was performed.

    Generates up to 3 RelayMetadata records:
        - nip66_rtt: Round-trip times (rtt_open, rtt_read, rtt_write, rtt_dns),
          network classification, and capability flags (is_open, is_readable, is_writable)
        - nip66_ssl: SSL certificate info (issuer, not_before, not_after, fingerprint)
        - nip66_geo: Geolocation (country_code, city, lat/lon, geohash, isp, asn)

    Example:
        >>> nip66 = await Nip66.fetch(relay, keys=keys, geo_reader=geo_db)
        >>> if nip66:
        ...     print(f"Openable: {nip66.is_open}, RTT: {nip66.rtt_open}ms")
        ...     print(f"Readable: {nip66.is_readable}")
        ...     if nip66.country_code:
        ...         print(f"Location: {nip66.country_code}")
    """

    relay: Relay
    rtt_metadata: Metadata  # RTT and network data (always present)
    ssl_metadata: Metadata | None  # SSL/TLS data (optional)
    geo_metadata: Metadata | None  # Geo data (optional)
    generated_at: int

    # --- Class-level defaults for test() ---
    _TEST_TIMEOUT: ClassVar[float] = 10.0

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
    def rtt_open(self) -> int | None:
        return self.rtt_metadata._get("rtt_open", expected_type=int)

    @property
    def rtt_read(self) -> int | None:
        return self.rtt_metadata._get("rtt_read", expected_type=int)

    @property
    def rtt_write(self) -> int | None:
        return self.rtt_metadata._get("rtt_write", expected_type=int)

    @property
    def rtt_dns(self) -> int | None:
        return self.rtt_metadata._get("rtt_dns", expected_type=int)

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
    def ssl_valid(self) -> bool | None:
        return (
            self.ssl_metadata._get("ssl_valid", expected_type=bool) if self.ssl_metadata else None
        )

    @property
    def ssl_issuer(self) -> str | None:
        return (
            self.ssl_metadata._get("ssl_issuer", expected_type=str) if self.ssl_metadata else None
        )

    @property
    def ssl_expires(self) -> int | None:
        return (
            self.ssl_metadata._get("ssl_expires", expected_type=int) if self.ssl_metadata else None
        )

    @property
    def has_ssl(self) -> bool:
        """Return True if SSL metadata is present."""
        return self.ssl_metadata is not None

    # --- Classification (in RTT metadata) ---

    @property
    def network(self) -> str | None:
        return self.rtt_metadata._get("network", expected_type=str)

    @property
    def relay_type(self) -> str | None:
        return self.rtt_metadata._get("relay_type", expected_type=str)

    @property
    def supported_nips(self) -> list[int]:
        return self.rtt_metadata._get("supported_nips", expected_type=list, default=[])

    @property
    def requirements(self) -> list[str]:
        return self.rtt_metadata._get("requirements", expected_type=list, default=[])

    @property
    def topics(self) -> list[str]:
        return self.rtt_metadata._get("topics", expected_type=list, default=[])

    @property
    def accepted_kinds(self) -> list[int]:
        return self.rtt_metadata._get("accepted_kinds", expected_type=list, default=[])

    @property
    def rejected_kinds(self) -> list[int]:
        return self.rtt_metadata._get("rejected_kinds", expected_type=list, default=[])

    # --- Geolocation ---

    @property
    def geohash(self) -> str | None:
        return self.geo_metadata._get("geohash", expected_type=str) if self.geo_metadata else None

    @property
    def geo_ip(self) -> str | None:
        return self.geo_metadata._get("geo_ip", expected_type=str) if self.geo_metadata else None

    @property
    def geo_country(self) -> str | None:
        return (
            self.geo_metadata._get("geo_country", expected_type=str) if self.geo_metadata else None
        )

    @property
    def geo_region(self) -> str | None:
        return (
            self.geo_metadata._get("geo_region", expected_type=str) if self.geo_metadata else None
        )

    @property
    def geo_city(self) -> str | None:
        return self.geo_metadata._get("geo_city", expected_type=str) if self.geo_metadata else None

    @property
    def geo_lat(self) -> float | None:
        return self.geo_metadata._get("geo_lat", expected_type=float) if self.geo_metadata else None

    @property
    def geo_lon(self) -> float | None:
        return self.geo_metadata._get("geo_lon", expected_type=float) if self.geo_metadata else None

    @property
    def geo_tz(self) -> str | None:
        return self.geo_metadata._get("geo_tz", expected_type=str) if self.geo_metadata else None

    @property
    def geo_asn(self) -> int | None:
        return self.geo_metadata._get("geo_asn", expected_type=int) if self.geo_metadata else None

    @property
    def geo_asn_org(self) -> str | None:
        return (
            self.geo_metadata._get("geo_asn_org", expected_type=str) if self.geo_metadata else None
        )

    @property
    def geo_isp(self) -> str | None:
        return self.geo_metadata._get("geo_isp", expected_type=str) if self.geo_metadata else None

    @property
    def has_geo(self) -> bool:
        """Return True if geo metadata is present."""
        return self.geo_metadata is not None

    # --- Internal test methods ---

    @staticmethod
    def _resolve_dns_sync(host: str) -> tuple[str, int]:
        """
        Synchronous DNS resolution.

        Returns:
            Tuple of (IP address, RTT in ms)

        Raises:
            socket.gaierror: DNS resolution failed
        """
        start = perf_counter()
        ip = socket.gethostbyname(host)
        rtt = int((perf_counter() - start) * 1000)
        return ip, rtt

    @classmethod
    async def _test_rtt(
        cls,
        relay: Relay,
        timeout: float,
        keys: Keys | None,
    ) -> Metadata:
        """
        Test relay RTT (round-trip times) and capabilities.

        Args:
            relay: Relay to test
            timeout: Connection timeout in seconds
            keys: Optional Keys for write test

        Returns:
            Metadata with rtt_open, rtt_read, rtt_write, rtt_dns, network

        Raises:
            Exception: Connection or test failures
        """
        data: dict[str, Any] = {"network": relay.network}

        # DNS resolution for clearnet relays
        if relay.network == "clearnet":
            try:
                ip, rtt_dns = await asyncio.to_thread(cls._resolve_dns_sync, relay.host)
                data["rtt_dns"] = rtt_dns
                data["_ip"] = ip  # Internal, used for geo lookup
            except socket.gaierror:
                pass

        # Create client (with or without signer)
        if keys:
            signer = NostrSigner.keys(keys._inner)
            client = Client(signer)
        else:
            client = Client()

        try:
            # Test open
            start = perf_counter()
            relay_url = RelayUrl.parse(relay.url)
            await client.add_relay(relay_url)
            await client.connect()
            data["rtt_open"] = int((perf_counter() - start) * 1000)

            # Test read
            try:
                start = perf_counter()
                f = Filter().limit(1)
                await client.fetch_events([f], timedelta(seconds=timeout))
                data["rtt_read"] = int((perf_counter() - start) * 1000)
            except Exception:
                pass

            # Test write (only if keys provided)
            # Use ephemeral kind (20000-29999) to avoid polluting relay
            if keys:
                try:
                    start = perf_counter()
                    builder = EventBuilder(Kind(20000), "")
                    output = await client.send_event_builder(builder)
                    if output:
                        data["rtt_write"] = int((perf_counter() - start) * 1000)
                except Exception:
                    pass

        finally:
            try:
                await client.shutdown()
            except Exception:
                pass

        return Metadata(data)

    @classmethod
    async def _test_ssl(
        cls,
        relay: Relay,
        timeout: float,
    ) -> Metadata:
        """
        Test SSL/TLS certificate.

        Args:
            relay: Relay to test (must be wss://)
            timeout: Connection timeout in seconds

        Returns:
            Metadata with ssl_valid, ssl_issuer, ssl_expires

        Raises:
            ValueError: Not a wss:// relay or not clearnet
            Exception: SSL connection failures
        """
        if relay.scheme != "wss":
            raise ValueError("SSL test requires wss:// scheme")
        if relay.network != "clearnet":
            raise ValueError("SSL test requires clearnet relay")

        port = relay.port or PORT_WSS
        data = await asyncio.to_thread(cls._check_ssl_sync, relay.host, port, timeout)

        if not data:
            raise ValueError("No SSL data collected")

        return Metadata(data)

    @staticmethod
    def _check_ssl_sync(host: str, port: int, timeout: float) -> dict[str, Any]:
        """Synchronous SSL check."""
        result: dict[str, Any] = {}

        context = ssl.create_default_context()
        with (
            socket.create_connection((host, port), timeout=timeout) as sock,
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
                    result["ssl_expires"] = ssl.cert_time_to_seconds(not_after)

            result["ssl_valid"] = True

        return result

    @classmethod
    async def _test_geo(
        cls,
        ip: str,
        city_db_path: str,
        asn_db_path: str | None = None,
    ) -> Metadata:
        """
        Lookup geolocation from IP address.

        Args:
            ip: IP address to lookup
            city_db_path: Path to GeoLite2-City database
            asn_db_path: Optional path to GeoLite2-ASN database

        Returns:
            Metadata with geo_ip, geo_country, geo_city, geo_lat, geo_lon, geohash, etc.

        Raises:
            Exception: GeoIP lookup failures
        """
        data = await asyncio.to_thread(cls._lookup_geo_sync, ip, city_db_path, asn_db_path)

        if len(data) <= 1:  # Only geo_ip, no actual geo data
            raise ValueError("No geolocation data found")

        return Metadata(data)

    @staticmethod
    def _lookup_geo_sync(
        ip: str,
        city_db_path: str,
        asn_db_path: str | None = None,
    ) -> dict[str, Any]:
        """Synchronous geolocation lookup."""
        result: dict[str, Any] = {"geo_ip": ip}

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

        if asn_db_path:
            with geoip2.database.Reader(asn_db_path) as reader:
                asn_response = reader.asn(ip)
                result["geo_asn"] = asn_response.autonomous_system_number
                result["geo_asn_org"] = asn_response.autonomous_system_organization

        return result

    # --- Factory method ---

    def to_relay_metadata(
        self,
    ) -> tuple["RelayMetadata", "RelayMetadata | None", "RelayMetadata | None"]:
        """
        Convert to RelayMetadata objects for database storage.

        Returns:
            Tuple of 3 elements (rtt, ssl, geo):
            - rtt: Always present (RTT and network data)
            - ssl: RelayMetadata if SSL data collected, None otherwise
            - geo: RelayMetadata if geo data collected, None otherwise
        """
        from .relay_metadata import MetadataType, RelayMetadata

        def make(metadata: Metadata, metadata_type: MetadataType) -> RelayMetadata:
            return RelayMetadata(
                relay=self.relay,
                metadata=metadata,
                metadata_type=metadata_type,
                generated_at=self.generated_at,
            )

        rtt = make(self.rtt_metadata, "nip66_rtt")
        ssl = make(self.ssl_metadata, "nip66_ssl") if self.ssl_metadata else None
        geo = make(self.geo_metadata, "nip66_geo") if self.geo_metadata else None

        return (rtt, ssl, geo)

    # --- Test ---

    @classmethod
    async def test(
        cls,
        relay: Relay,
        timeout: float | None = None,
        keys: Keys | None = None,
        city_db_path: str | None = None,
        asn_db_path: str | None = None,
    ) -> "Nip66":
        """
        Test relay and collect NIP-66 monitoring data.

        Args:
            relay: Relay object to test
            timeout: Connection timeout in seconds (default: _TEST_TIMEOUT)
            keys: Optional Keys for write test
            city_db_path: Path to GeoLite2-City database
            asn_db_path: Optional path to GeoLite2-ASN database

        Returns:
            Nip66 instance with test results
        """
        timeout = timeout if timeout is not None else cls._TEST_TIMEOUT

        # RTT test (always performed)
        rtt_metadata = await cls._test_rtt(relay, timeout, keys)

        # Extract IP from RTT metadata for geo lookup
        ip = rtt_metadata._get("_ip", expected_type=str)

        # SSL test (clearnet wss:// only)
        ssl_metadata: Metadata | None = None
        try:
            ssl_metadata = await cls._test_ssl(relay, timeout)
        except Exception:
            pass

        # Geo test (clearnet with IP and db path)
        geo_metadata: Metadata | None = None
        if ip and city_db_path:
            try:
                geo_metadata = await cls._test_geo(ip, city_db_path, asn_db_path)
            except Exception:
                pass

        # Remove internal _ip field from RTT metadata
        rtt_data = {k: v for k, v in rtt_metadata.data.items() if not k.startswith("_")}

        return cls(
            relay=relay,
            rtt_metadata=Metadata(rtt_data),
            ssl_metadata=ssl_metadata,
            geo_metadata=geo_metadata,
            generated_at=int(time()),
        )
