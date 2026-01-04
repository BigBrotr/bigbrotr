"""
NIP-66 Relay Monitoring and Discovery.

This module provides the Nip66 class for testing relay capabilities and collecting
monitoring data per NIP-66 specification. Tests relay connectivity (open, read, write),
collects SSL certificate info, and performs geolocation lookup.

See: https://github.com/nostr-protocol/nips/blob/master/66.md

Complete NIP-66 metadata structures::

    # RTT (Round-Trip Time) metadata - optional, present if any test succeeded
    rtt_metadata = {
        "rtt_open": 150,  # Connection time in ms
        "rtt_read": 200,  # Read test time in ms
        "rtt_write": 180,  # Write test time in ms
        "rtt_dns": 50,  # DNS resolution time in ms (clearnet only)
    }
    # Note: network type (clearnet/tor/i2p/loki) is from relay.network, not in metadata

    # SSL metadata - optional, clearnet wss:// only
    ssl_metadata = {
        "ssl_valid": True,  # Certificate is valid
        "ssl_issuer": "Let's Encrypt",  # Certificate issuer organization
        "ssl_expires": 1735689600,  # Certificate expiry timestamp
    }

    # Geo metadata - optional, requires GeoIP database
    geo_metadata = {
        "geo_ip": "1.2.3.4",  # Resolved IP address
        "geo_country": "US",  # ISO country code
        "geo_region": "California",  # Region/state name
        "geo_city": "San Francisco",  # City name
        "geo_lat": 37.7749,  # Latitude
        "geo_lon": -122.4194,  # Longitude
        "geo_tz": "America/Los_Angeles",  # Timezone
        "geohash": "9q8yyk8yu",  # NIP-52 geohash
        "geo_asn": 13335,  # Autonomous System Number
        "geo_asn_org": "Cloudflare",  # ASN organization name
    }

Usage::

    # Full test with all features
    city_reader = geoip2.database.Reader("/path/to/GeoLite2-City.mmdb")
    keys = Keys.generate()
    event_builder = EventBuilder.text_note("test")

    nip66 = await Nip66.test(
        relay, keys=keys, event_builder=event_builder, city_reader=city_reader
    )

    # RTT + SSL only (no geo)
    nip66 = await Nip66.test(
        relay, keys=keys, event_builder=event_builder, run_geo=False
    )

    # Geo only (no RTT/SSL)
    nip66 = await Nip66.test(
        relay, city_reader=city_reader, run_rtt=False, run_ssl=False
    )

    # Access results
    print(f"Open: {nip66.is_openable}, RTT: {nip66.rtt_open}ms")
    if nip66.has_geo:
        print(f"Location: {nip66.geo_country}/{nip66.geo_city}")

    # Convert for database storage (up to 3 RelayMetadata objects)
    rtt, ssl, geo = nip66.to_relay_metadata()

    # Close readers when done
    city_reader.close()
"""

from __future__ import annotations

import asyncio
import socket
import ssl
from dataclasses import dataclass, field
from datetime import timedelta
from time import perf_counter, time
from typing import TYPE_CHECKING, Any, ClassVar, TypedDict, get_type_hints

import geohash2
import geoip2.database  # noqa: TC002 - used at runtime in _lookup_geo_sync
from nostr_sdk import Client, EventBuilder, Filter, NostrSigner, RelayUrl

from .metadata import Metadata
from .relay import Relay


if TYPE_CHECKING:
    from .keys import Keys
    from .relay_metadata import RelayMetadata


# --- TypedDicts for NIP-66 structure ---
#
# These TypedDicts define the expected schema for NIP-66 metadata.
# They are used for type validation in _parse_metadata(): fields with
# incorrect types are silently dropped to ensure data integrity.
# All fields are optional (total=False) since each test may partially succeed.


class Nip66RttData(TypedDict, total=False):
    """
    RTT (Round-Trip Time) metadata per NIP-66.

    All fields are optional - only present if the corresponding test succeeded.
    Used for type validation: values with incorrect types are silently dropped.
    """

    rtt_open: int  # Connection time in ms
    rtt_read: int  # Read test time in ms
    rtt_write: int  # Write test time in ms
    rtt_dns: int  # DNS resolution time in ms (clearnet only)


class Nip66SslData(TypedDict, total=False):
    """
    SSL/TLS metadata per NIP-66.

    All fields are optional - only applicable for clearnet wss:// relays.
    Used for type validation: values with incorrect types are silently dropped.
    """

    ssl_valid: bool  # Certificate is valid
    ssl_issuer: str  # Certificate issuer organization
    ssl_expires: int  # Certificate expiry unix timestamp


class Nip66GeoData(TypedDict, total=False):
    """
    Geolocation metadata per NIP-66.

    All fields are optional - requires GeoIP database and successful DNS resolution.
    Used for type validation: values with incorrect types are silently dropped.
    """

    geo_ip: str  # Resolved IP address
    geo_country: str  # ISO country code
    geo_region: str  # Region/state name
    geo_city: str  # City name
    geo_lat: float  # Latitude
    geo_lon: float  # Longitude
    geo_tz: str  # Timezone identifier
    geohash: str  # NIP-52 geohash (9 chars precision)
    geo_asn: int  # Autonomous System Number
    geo_asn_org: str  # ASN organization name


# --- Exception ---


class Nip66TestError(Exception):
    """Error testing relay for NIP-66 monitoring data."""

    def __init__(self, relay: Relay, cause: Exception) -> None:
        self.relay = relay
        self.cause = cause
        super().__init__(f"Failed to test NIP-66 for {relay.url}: {cause}")


# --- Main class ---


@dataclass(frozen=True, slots=True)
class Nip66:
    """
    Immutable NIP-66 relay monitoring data.

    Tests relay capabilities (open, read, write) and collects monitoring metrics
    including round-trip times, SSL certificate data, and geolocation info.
    Generates up to 3 RelayMetadata objects for database storage.

    Accepts dict or Metadata for each metadata field - parsing happens in __post_init__.

    Attributes:
        relay: The Relay being monitored.
        rtt_metadata: RTT data (optional, present if any test succeeded).
        ssl_metadata: SSL/TLS certificate data (optional, clearnet wss:// only).
        geo_metadata: Geolocation data (optional, requires GeoIP database).
        generated_at: Unix timestamp when monitoring was performed (default: now).

    Properties (RTT):
        rtt_open, rtt_read, rtt_write, rtt_dns: Round-trip times in ms.
        network: Network type from relay (clearnet, tor, i2p, loki).
        has_rtt: True if RTT metadata present.
        is_openable, is_readable, is_writable: Capability flags.

    Properties (SSL):
        ssl_valid, ssl_issuer, ssl_expires: Certificate info.
        has_ssl: True if SSL metadata present.

    Properties (Geo):
        geo_ip, geo_country, geo_region, geo_city: Location info.
        geo_lat, geo_lon, geohash: Coordinates.
        geo_tz, geo_asn, geo_asn_org: Additional geo data.
        has_geo: True if geo metadata present.
    """

    relay: Relay
    rtt_metadata: Metadata | None = None  # Raw or parsed, validated in __post_init__
    ssl_metadata: Metadata | None = None  # Raw or parsed, validated in __post_init__
    geo_metadata: Metadata | None = None  # Raw or parsed, validated in __post_init__
    generated_at: int = field(default_factory=lambda: int(time()))

    def __post_init__(self) -> None:
        """Parse and validate all metadata fields."""
        object.__setattr__(
            self, "rtt_metadata", self._parse_metadata(self.rtt_metadata, Nip66RttData)
        )
        object.__setattr__(
            self, "ssl_metadata", self._parse_metadata(self.ssl_metadata, Nip66SslData)
        )
        object.__setattr__(
            self, "geo_metadata", self._parse_metadata(self.geo_metadata, Nip66GeoData)
        )

        # At least one metadata must be present
        if not (self.rtt_metadata or self.ssl_metadata or self.geo_metadata):
            raise ValueError("At least one metadata (rtt, ssl, or geo) must be provided")

    @classmethod
    def _parse_metadata(
        cls, data: Metadata | dict[str, Any] | None, typed_dict: type
    ) -> Metadata | None:
        """Parse and validate metadata, keeping only valid fields."""
        if data is None:
            return None

        raw = data.data if isinstance(data, Metadata) else data
        result: dict[str, Any] = {}

        for key, expected_type in get_type_hints(typed_dict).items():
            val = raw.get(key)
            if isinstance(val, expected_type):
                result[key] = val

        return Metadata(result) if result else None

    # --- Class-level defaults ---
    _DEFAULT_TEST_TIMEOUT: ClassVar[float] = 10.0

    # --- Helper for metadata access ---

    def _get_rtt(self, key: str) -> int | None:
        """Get RTT metadata value by key."""
        return self.rtt_metadata.data.get(key) if self.rtt_metadata else None

    def _get_ssl(self, key: str) -> Any:
        """Get SSL metadata value by key."""
        return self.ssl_metadata.data.get(key) if self.ssl_metadata else None

    def _get_geo(self, key: str) -> Any:
        """Get geo metadata value by key."""
        return self.geo_metadata.data.get(key) if self.geo_metadata else None

    # --- RTT properties ---

    @property
    def rtt_open(self) -> int | None:
        """Connection round-trip time in milliseconds."""
        return self._get_rtt("rtt_open")

    @property
    def rtt_read(self) -> int | None:
        """Read test round-trip time in milliseconds."""
        return self._get_rtt("rtt_read")

    @property
    def rtt_write(self) -> int | None:
        """Write test round-trip time in milliseconds."""
        return self._get_rtt("rtt_write")

    @property
    def rtt_dns(self) -> int | None:
        """DNS resolution time in milliseconds."""
        return self._get_rtt("rtt_dns")

    @property
    def has_rtt(self) -> bool:
        """True if RTT metadata is present."""
        return self.rtt_metadata is not None

    @property
    def is_openable(self) -> bool:
        """True if relay connection succeeded."""
        return self.rtt_open is not None

    @property
    def is_readable(self) -> bool:
        """True if relay read test succeeded."""
        return self.rtt_read is not None

    @property
    def is_writable(self) -> bool:
        """True if relay write test succeeded."""
        return self.rtt_write is not None

    # --- SSL properties ---

    @property
    def ssl_valid(self) -> bool | None:
        """True if SSL certificate is valid."""
        return self._get_ssl("ssl_valid")

    @property
    def ssl_issuer(self) -> str | None:
        """SSL certificate issuer organization."""
        return self._get_ssl("ssl_issuer")

    @property
    def ssl_expires(self) -> int | None:
        """SSL certificate expiry unix timestamp."""
        return self._get_ssl("ssl_expires")

    @property
    def has_ssl(self) -> bool:
        """True if SSL metadata is present."""
        return self.ssl_metadata is not None

    # --- Geo properties ---

    @property
    def geo_ip(self) -> str | None:
        """Resolved IP address."""
        return self._get_geo("geo_ip")

    @property
    def geo_country(self) -> str | None:
        """ISO country code."""
        return self._get_geo("geo_country")

    @property
    def geo_region(self) -> str | None:
        """Region or state name."""
        return self._get_geo("geo_region")

    @property
    def geo_city(self) -> str | None:
        """City name."""
        return self._get_geo("geo_city")

    @property
    def geo_lat(self) -> float | None:
        """Latitude coordinate."""
        return self._get_geo("geo_lat")

    @property
    def geo_lon(self) -> float | None:
        """Longitude coordinate."""
        return self._get_geo("geo_lon")

    @property
    def geo_tz(self) -> str | None:
        """Timezone identifier."""
        return self._get_geo("geo_tz")

    @property
    def geohash(self) -> str | None:
        """NIP-52 geohash (9 characters precision)."""
        return self._get_geo("geohash")

    @property
    def geo_asn(self) -> int | None:
        """Autonomous System Number."""
        return self._get_geo("geo_asn")

    @property
    def geo_asn_org(self) -> str | None:
        """Autonomous System organization name."""
        return self._get_geo("geo_asn_org")

    @property
    def has_geo(self) -> bool:
        """True if geo metadata is present."""
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
        keys: Keys,
        event_builder: EventBuilder,
    ) -> Metadata:
        """
        Test relay RTT (round-trip times) and capabilities.

        Returns:
            Metadata with RTT data if any test succeeded, None if no data collected.
        """
        data: dict[str, Any] = {}

        # DNS resolution for clearnet relays
        if relay.network == "clearnet":
            try:
                _, rtt_dns = await asyncio.to_thread(cls._resolve_dns_sync, relay.host)
                data["rtt_dns"] = rtt_dns
            except socket.gaierror:
                pass

        # Create client with signer
        signer = NostrSigner.keys(keys._inner)
        client = Client(signer)

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

            # Test write
            try:
                start = perf_counter()
                output = await client.send_event_builder(event_builder)
                if output:
                    data["rtt_write"] = int((perf_counter() - start) * 1000)
            except Exception:
                pass

        except Exception:
            # Connection failed - return data collected so far (e.g., rtt_dns)
            pass
        finally:
            try:
                await client.shutdown()
            except Exception:
                pass

        return Metadata(data)

    @classmethod
    async def _test_ssl(cls, relay: Relay, timeout: float) -> Metadata:
        """
        Test SSL/TLS certificate.

        Returns:
            Metadata with SSL data (may be empty if not applicable).
        """
        data: dict[str, Any] = {}

        if relay.scheme == "wss" and relay.network == "clearnet":
            port = relay.port or Relay._PORT_WSS
            data = await asyncio.to_thread(cls._check_ssl_sync, relay.host, port, timeout)

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
                issuer = cert.get("issuer", ())
                for rdn in issuer:  # type: ignore[union-attr]
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
        relay: Relay,
        city_reader: geoip2.database.Reader | None,
        asn_reader: geoip2.database.Reader | None = None,
    ) -> Metadata:
        """
        Lookup geolocation for relay.

        Args:
            relay: Relay to lookup.
            city_reader: Pre-opened GeoLite2-City database reader.
            asn_reader: Optional pre-opened GeoLite2-ASN database reader.

        Returns:
            Metadata with geo data (may be empty if not applicable).
        """
        data: dict[str, Any] = {}

        if relay.network == "clearnet" and city_reader:
            # Resolve DNS to get IP
            try:
                ip, _ = await asyncio.to_thread(cls._resolve_dns_sync, relay.host)
                data = await asyncio.to_thread(cls._lookup_geo_sync, ip, city_reader, asn_reader)
                # Only geo_ip is set, no actual geo data found
                if len(data) <= 1:
                    data = {}
            except socket.gaierror:
                pass

        return Metadata(data)

    @staticmethod
    def _lookup_geo_sync(
        ip: str,
        city_reader: geoip2.database.Reader,
        asn_reader: geoip2.database.Reader | None = None,
    ) -> dict[str, Any]:
        """
        Synchronous geolocation lookup using pre-opened readers.

        Args:
            ip: IP address to lookup.
            city_reader: Pre-opened GeoLite2-City database reader.
            asn_reader: Optional pre-opened GeoLite2-ASN database reader.

        Returns:
            Dict with geo data (at minimum geo_ip).
        """
        result: dict[str, Any] = {"geo_ip": ip}

        response = city_reader.city(ip)

        # Only add non-None values
        if response.country.iso_code:
            result["geo_country"] = response.country.iso_code
        if response.city.name:
            result["geo_city"] = response.city.name
        if response.location.latitude is not None:
            result["geo_lat"] = response.location.latitude
        if response.location.longitude is not None:
            result["geo_lon"] = response.location.longitude
        if response.location.time_zone:
            result["geo_tz"] = response.location.time_zone
        if response.subdivisions:
            region = response.subdivisions.most_specific.name
            if region:
                result["geo_region"] = region

        # Generate geohash if coordinates available
        if "geo_lat" in result and "geo_lon" in result:
            result["geohash"] = geohash2.encode(
                result["geo_lat"],
                result["geo_lon"],
                precision=9,
            )

        if asn_reader:
            asn_response = asn_reader.asn(ip)
            if asn_response.autonomous_system_number:
                result["geo_asn"] = asn_response.autonomous_system_number
            if asn_response.autonomous_system_organization:
                result["geo_asn_org"] = asn_response.autonomous_system_organization

        return result

    # --- Factory method ---

    def to_relay_metadata(
        self,
    ) -> tuple[RelayMetadata | None, RelayMetadata | None, RelayMetadata | None]:
        """
        Convert to RelayMetadata objects for database storage.

        Returns:
            Tuple of (rtt, ssl, geo):
            - rtt: RelayMetadata if RTT data collected, None otherwise
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

        rtt_result = make(self.rtt_metadata, MetadataType.NIP66_RTT) if self.rtt_metadata else None
        ssl_result = make(self.ssl_metadata, MetadataType.NIP66_SSL) if self.ssl_metadata else None
        geo_result = make(self.geo_metadata, MetadataType.NIP66_GEO) if self.geo_metadata else None

        return (rtt_result, ssl_result, geo_result)

    # --- Main test method ---

    @classmethod
    async def test(
        cls,
        relay: Relay,
        timeout: float | None = None,
        keys: Keys | None = None,
        event_builder: EventBuilder | None = None,
        city_reader: geoip2.database.Reader | None = None,
        asn_reader: geoip2.database.Reader | None = None,
        run_rtt: bool = True,
        run_ssl: bool = True,
        run_geo: bool = True,
    ) -> Nip66:
        """
        Test relay and collect NIP-66 monitoring data.

        All tests are enabled by default. Disable specific tests with run_* flags.
        At least one test must succeed to create a valid Nip66 instance.

        Args:
            relay: Relay object to test
            timeout: Connection timeout in seconds (default: _DEFAULT_TEST_TIMEOUT)
            keys: Keys for signing test events (required if run_rtt=True)
            event_builder: EventBuilder for write test (required if run_rtt=True)
            city_reader: Pre-opened GeoLite2-City database reader for geo lookup
            asn_reader: Optional pre-opened GeoLite2-ASN database reader
            run_rtt: Run RTT test (open/read/write). Requires keys and event_builder.
            run_ssl: Run SSL certificate test (clearnet wss:// only)
            run_geo: Run geolocation test. Requires city_reader.

        Returns:
            Nip66 instance with test results

        Raises:
            Nip66TestError: If all tests fail and no metadata collected
            ValueError: If run_rtt=True but keys/event_builder not provided
            asyncio.CancelledError: If the task was cancelled
            KeyboardInterrupt: If interrupted by user
            SystemExit: If system exit requested

        Example:
            # Full test with all features
            city_reader = geoip2.database.Reader("/path/to/GeoLite2-City.mmdb")
            keys = Keys.generate()
            event_builder = EventBuilder.text_note("test")
            nip66 = await Nip66.test(relay, keys=keys, event_builder=event_builder,
                                     city_reader=city_reader)

            # RTT only (no geo)
            nip66 = await Nip66.test(relay, keys=keys, event_builder=event_builder,
                                     run_geo=False)

            # Geo only (no RTT/SSL)
            nip66 = await Nip66.test(relay, city_reader=city_reader,
                                     run_rtt=False, run_ssl=False)
        """
        # Validate required parameters
        if run_rtt and (keys is None or event_builder is None):
            raise ValueError("run_rtt=True requires keys and event_builder")

        timeout = timeout if timeout is not None else cls._DEFAULT_TEST_TIMEOUT

        # Build list of tasks to run
        tasks: list[Any] = []
        task_names: list[str] = []

        if run_rtt and keys and event_builder:
            tasks.append(cls._test_rtt(relay, timeout, keys, event_builder))
            task_names.append("rtt")
        if run_ssl:
            tasks.append(cls._test_ssl(relay, timeout))
            task_names.append("ssl")
        if run_geo:
            tasks.append(cls._test_geo(relay, city_reader, asn_reader))
            task_names.append("geo")

        # Run selected tests in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Map results back to metadata types
        rtt_metadata: Metadata | None = None
        ssl_metadata: Metadata | None = None
        geo_metadata: Metadata | None = None

        for name, result in zip(task_names, results, strict=True):
            if isinstance(result, BaseException):
                continue
            if name == "rtt":
                rtt_metadata = result
            elif name == "ssl":
                ssl_metadata = result
            elif name == "geo":
                geo_metadata = result

        try:
            return cls(
                relay=relay,
                rtt_metadata=rtt_metadata,
                ssl_metadata=ssl_metadata,
                geo_metadata=geo_metadata,
            )
        except ValueError as e:
            raise Nip66TestError(relay, e) from e
