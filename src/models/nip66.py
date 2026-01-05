"""
NIP-66 Relay Monitoring and Discovery.

This module provides the Nip66 class for testing relay capabilities and collecting
monitoring data per NIP-66 specification. Tests relay connectivity (open, read, write),
collects SSL certificate info, DNS records, HTTP headers, and performs geolocation lookup.

See: https://github.com/nostr-protocol/nips/blob/master/66.md

Complete NIP-66 metadata structures::

    # RTT (Round-Trip Time) metadata - optional, present if any test succeeded
    rtt_metadata = {
        "rtt_open": 150,  # Connection time in ms
        "rtt_read": 200,  # Read test time in ms
        "rtt_write": 180,  # Write test time in ms
    }

    # SSL metadata - optional, clearnet wss:// only
    ssl_metadata = {
        "ssl_valid": True,  # Certificate is valid
        "ssl_subject_cn": "relay.example.com",  # Subject Common Name
        "ssl_issuer": "Let's Encrypt",  # Issuer organization
        "ssl_issuer_cn": "R3",  # Issuer Common Name
        "ssl_expires": 1735689600,  # Expiry timestamp
        "ssl_not_before": 1727827200,  # Start validity timestamp
        "ssl_san": ["relay.example.com"],  # Subject Alternative Names
        "ssl_serial": "04:AB:CD:EF:...",  # Serial number (hex)
        "ssl_version": 3,  # X.509 version
        "ssl_fingerprint": "SHA256:AB12...",  # SHA-256 fingerprint
        "ssl_protocol": "TLSv1.3",  # TLS protocol version
        "ssl_cipher": "TLS_AES_256_GCM_SHA384",  # Cipher suite
        "ssl_cipher_bits": 256,  # Cipher strength in bits
    }

    # Geo metadata - optional, requires GeoIP database
    geo_metadata = {
        "geo_ip": "1.2.3.4",  # Resolved IP address
        "geo_country": "US",  # ISO country code
        "geo_country_name": "United States",  # Full country name
        "geo_continent": "NA",  # Continent code
        "geo_continent_name": "North America",  # Full continent name
        "geo_is_eu": False,  # Is in European Union
        "geo_region": "California",  # Region/state name
        "geo_city": "San Francisco",  # City name
        "geo_postal": "94102",  # Postal code
        "geo_lat": 37.7749,  # Latitude
        "geo_lon": -122.4194,  # Longitude
        "geo_accuracy": 10,  # Accuracy radius in km
        "geo_tz": "America/Los_Angeles",  # Timezone
        "geohash": "9q8yyk8yu",  # NIP-52 geohash
        "geo_geoname_id": 5391959,  # GeoNames ID
        "geo_asn": 13335,  # Autonomous System Number
        "geo_asn_org": "Cloudflare",  # ASN organization name
        "geo_network": "1.2.3.0/24",  # Network CIDR
    }

    # DNS metadata - optional, clearnet only
    dns_metadata = {
        "dns_ip": "1.2.3.4",  # Primary IPv4 address
        "dns_ipv6": "2606:4700::1",  # Primary IPv6 address
        "dns_ips": ["1.2.3.4", "1.2.3.5"],  # All A record IPs
        "dns_ips_v6": ["2606:4700::1"],  # All AAAA record IPs
        "dns_cname": "proxy.example.com",  # CNAME if present
        "dns_reverse": "server1.example.com",  # Reverse DNS (PTR)
        "dns_ns": ["ns1.cloudflare.com"],  # Nameservers
        "dns_ttl": 300,  # TTL in seconds
        "dns_rtt": 50,  # DNS resolution time in ms
    }

    # HTTP metadata - optional, from WebSocket upgrade
    http_metadata = {
        "http_server": "nginx/1.24.0",  # Server header
        "http_powered_by": "Strfry",  # X-Powered-By header
    }

Usage::

    # Full test with all features
    city_reader = geoip2.database.Reader("/path/to/GeoLite2-City.mmdb")
    asn_reader = geoip2.database.Reader("/path/to/GeoLite2-ASN.mmdb")
    keys = Keys.generate()
    event_builder = EventBuilder.text_note("test")

    nip66 = await Nip66.test(
        relay,
        keys=keys,
        event_builder=event_builder,
        city_reader=city_reader,
        asn_reader=asn_reader,
    )

    # Access results via metadata dicts
    if nip66.rtt_metadata:
        print(f"Open RTT: {nip66.rtt_metadata.data.get('rtt_open')}ms")
    if nip66.geo_metadata:
        print(f"Location: {nip66.geo_metadata.data.get('geo_country')}")

    # Convert for database storage (up to 5 RelayMetadata objects)
    rtt, ssl, geo, dns, http = nip66.to_relay_metadata()
"""

from __future__ import annotations

import asyncio
import hashlib
import socket
import ssl
from dataclasses import dataclass, field
from datetime import timedelta
from time import perf_counter, time
from typing import TYPE_CHECKING, Any, ClassVar, TypedDict

import dns.resolver  # type: ignore[import-not-found]
import geohash2
import geoip2.database  # noqa: TC002 - used at runtime in _lookup_geo_sync
from nostr_sdk import ClientBuilder, ClientOptions, EventBuilder, Filter, NostrSigner, RelayUrl

from .metadata import Metadata
from .relay import Relay
from .utils import parse_typed_dict


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
    """RTT (Round-Trip Time) metadata per NIP-66."""

    rtt_open: int  # Connection time in ms
    rtt_read: int  # Read test time in ms
    rtt_write: int  # Write test time in ms


class Nip66SslData(TypedDict, total=False):
    """SSL/TLS metadata per NIP-66."""

    ssl_valid: bool  # Certificate is valid
    ssl_subject_cn: str  # Subject Common Name
    ssl_issuer: str  # Issuer organization
    ssl_issuer_cn: str  # Issuer Common Name
    ssl_expires: int  # Expiry unix timestamp
    ssl_not_before: int  # Start validity unix timestamp
    ssl_san: list[str]  # Subject Alternative Names
    ssl_serial: str  # Serial number (hex format)
    ssl_version: int  # X.509 version (usually 3)
    ssl_fingerprint: str  # SHA-256 fingerprint
    ssl_protocol: str  # TLS protocol version
    ssl_cipher: str  # Cipher suite name
    ssl_cipher_bits: int  # Cipher strength in bits


class Nip66GeoData(TypedDict, total=False):
    """Geolocation metadata per NIP-66."""

    geo_ip: str  # Resolved IP address
    geo_country: str  # ISO country code
    geo_country_name: str  # Full country name
    geo_continent: str  # Continent code (NA, EU, AS, etc.)
    geo_continent_name: str  # Full continent name
    geo_is_eu: bool  # Is in European Union
    geo_region: str  # Region/state name
    geo_city: str  # City name
    geo_postal: str  # Postal code
    geo_lat: float  # Latitude
    geo_lon: float  # Longitude
    geo_accuracy: int  # Accuracy radius in km
    geo_tz: str  # Timezone identifier
    geohash: str  # NIP-52 geohash (9 chars precision)
    geo_geoname_id: int  # GeoNames ID
    geo_asn: int  # Autonomous System Number
    geo_asn_org: str  # ASN organization name
    geo_network: str  # Network CIDR


class Nip66DnsData(TypedDict, total=False):
    """DNS metadata per NIP-66."""

    dns_ip: str  # Primary IPv4 address
    dns_ipv6: str  # Primary IPv6 address
    dns_ips: list[str]  # All A record IPs
    dns_ips_v6: list[str]  # All AAAA record IPs
    dns_cname: str  # CNAME record if present
    dns_reverse: str  # Reverse DNS (PTR record)
    dns_ns: list[str]  # Nameservers
    dns_ttl: int  # TTL in seconds
    dns_rtt: int  # DNS resolution time in ms


class Nip66HttpData(TypedDict, total=False):
    """HTTP metadata per NIP-66 (from WebSocket upgrade)."""

    http_server: str  # Server header
    http_powered_by: str  # X-Powered-By header


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
    including round-trip times, SSL certificate data, DNS records, HTTP headers,
    and geolocation info. Generates up to 5 RelayMetadata objects for database storage.

    Attributes:
        relay: The Relay being monitored.
        rtt_metadata: RTT data (optional, present if any test succeeded).
        ssl_metadata: SSL/TLS certificate data (optional, clearnet wss:// only).
        geo_metadata: Geolocation data (optional, requires GeoIP database).
        dns_metadata: DNS resolution data (optional, clearnet only).
        http_metadata: HTTP headers data (optional, from WebSocket upgrade).
        generated_at: Unix timestamp when monitoring was performed (default: now).

    Access metadata fields directly via metadata.data dict:
        nip66.rtt_metadata.data.get('rtt_open')
        nip66.ssl_metadata.data.get('ssl_issuer')
        nip66.geo_metadata.data.get('geo_country')
    """

    relay: Relay
    rtt_metadata: Metadata | None = None
    ssl_metadata: Metadata | None = None
    geo_metadata: Metadata | None = None
    dns_metadata: Metadata | None = None
    http_metadata: Metadata | None = None
    generated_at: int = field(default_factory=lambda: int(time()))

    def __post_init__(self) -> None:
        """Parse and validate all metadata fields.

        Metadata with all None values becomes None.
        Raises ValueError if all metadata are None.
        """
        object.__setattr__(self, "rtt_metadata", self._to_metadata(self.rtt_metadata, Nip66RttData))
        object.__setattr__(self, "ssl_metadata", self._to_metadata(self.ssl_metadata, Nip66SslData))
        object.__setattr__(self, "geo_metadata", self._to_metadata(self.geo_metadata, Nip66GeoData))
        object.__setattr__(self, "dns_metadata", self._to_metadata(self.dns_metadata, Nip66DnsData))
        object.__setattr__(
            self, "http_metadata", self._to_metadata(self.http_metadata, Nip66HttpData)
        )

        # Check that at least one metadata has data
        if all(
            m is None
            for m in [
                self.rtt_metadata,
                self.ssl_metadata,
                self.geo_metadata,
                self.dns_metadata,
                self.http_metadata,
            ]
        ):
            raise ValueError("At least one NIP-66 metadata must have data")

    @classmethod
    def _to_metadata(cls, data: Metadata | dict[str, Any] | None, schema: type) -> Metadata | None:
        """Convert data to Metadata with schema validation.

        Returns None if all values are None (empty metadata).

        Uses parse_typed_dict for validation:
        - All schema keys are included in result (missing = None)
        - Invalid types are normalized to None
        - Empty strings/lists are normalized to None
        - List elements with invalid types are filtered out
        """
        if data is None:
            return None

        raw = data.data if isinstance(data, Metadata) else data
        if not raw:
            return None

        # Parse against schema using shared function
        parsed = parse_typed_dict(raw, schema)

        # If all values are None, return None
        if all(v is None for v in parsed.values()):
            return None

        return Metadata(parsed)

    # --- Convenience properties for common fields ---

    @property
    def rtt_open(self) -> int | None:
        """Round-trip time to open connection (milliseconds)."""
        if self.rtt_metadata is None:
            return None
        return self.rtt_metadata.data.get("rtt_open")

    @property
    def rtt_read(self) -> int | None:
        """Round-trip time to read event (milliseconds)."""
        if self.rtt_metadata is None:
            return None
        return self.rtt_metadata.data.get("rtt_read")

    @property
    def rtt_write(self) -> int | None:
        """Round-trip time to write event (milliseconds)."""
        if self.rtt_metadata is None:
            return None
        return self.rtt_metadata.data.get("rtt_write")

    @property
    def geohash(self) -> str | None:
        """Geohash of relay location."""
        if self.geo_metadata is None:
            return None
        return self.geo_metadata.data.get("geo_geohash")

    @property
    def is_openable(self) -> bool:
        """Whether relay connection succeeded (has rtt_open)."""
        return self.rtt_open is not None

    # --- Class-level defaults ---
    _DEFAULT_TEST_TIMEOUT: ClassVar[float] = 10.0

    # --- Internal test methods ---

    @classmethod
    async def _test_rtt(
        cls,
        relay: Relay,
        timeout: float,
        keys: Keys,
        event_builder: EventBuilder,
        proxy_url: str | None = None,
    ) -> Metadata:
        """Test relay RTT (round-trip times) and capabilities.

        Args:
            relay: Relay to test
            timeout: Connection timeout in seconds
            keys: Keys for signing test events
            event_builder: EventBuilder for write test
            proxy_url: Optional SOCKS5 proxy URL for overlay networks
        """
        data: dict[str, Any] = {}

        # Create client with signer and optional proxy
        signer = NostrSigner.keys(keys._inner)
        opts = ClientOptions()
        if proxy_url:
            opts = opts.proxy(proxy_url)
        client = ClientBuilder().signer(signer).opts(opts).build()

        try:
            # Test open
            relay_url = RelayUrl.parse(relay.url)
            await client.add_relay(relay_url)

            # connect() returns immediately, use wait_for_connection() to measure actual RTT
            await client.connect()
            start = perf_counter()
            await client.wait_for_connection(timedelta(seconds=timeout))
            rtt_open = int((perf_counter() - start) * 1000)

            # Check if actually connected
            relay_obj = await client.relay(relay_url)
            status = relay_obj.status()
            if str(status) != "RelayStatus.CONNECTED":
                raise ConnectionError(f"Relay not connected: {status}")

            data["rtt_open"] = rtt_open

            # Test read
            try:
                start = perf_counter()
                f = Filter().limit(1)
                await client.fetch_events(f, timedelta(seconds=timeout))
                rtt_read = int((perf_counter() - start) * 1000)

                # Validate read: if rtt_read >= timeout, it means we waited the full timeout
                # without receiving any response (connection not working)
                timeout_ms = int(timeout * 1000)
                if rtt_read < timeout_ms:
                    data["rtt_read"] = rtt_read
            except Exception:
                pass

            # Test write
            try:
                start = perf_counter()
                output = await client.send_event_builder(event_builder)
                rtt_write = int((perf_counter() - start) * 1000)

                # Validate write: if output exists and rtt_write > 0, it's likely valid
                # rtt_write < 1 with output is suspicious (too fast for network roundtrip)
                if output and rtt_write >= 1:
                    data["rtt_write"] = rtt_write
            except Exception:
                pass

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
        """Test SSL/TLS certificate and connection details.

        Note: SSL test requires direct socket connection, not supported via proxy.
        Only works for clearnet wss:// relays.
        """
        data: dict[str, Any] = {}

        if relay.scheme != "wss" or relay.network != "clearnet":
            return Metadata(data)

        port = relay.port or Relay._PORT_WSS
        try:
            data = await asyncio.to_thread(cls._check_ssl_sync, relay.host, port, timeout)
        except Exception:
            pass

        return Metadata(data)

    @staticmethod
    def _check_ssl_sync(host: str, port: int, timeout: float) -> dict[str, Any]:
        """Synchronous SSL check with comprehensive certificate extraction.

        Connects without verification to extract certificate data even if
        the certificate is expired, self-signed, or has other issues.
        Then validates the certificate separately to set ssl_valid.
        """
        result: dict[str, Any] = {}

        # Connect without verification to get certificate data
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        with (
            socket.create_connection((host, port), timeout=timeout) as sock,
            context.wrap_socket(sock, server_hostname=host) as ssock,
        ):
            cert = ssock.getpeercert()
            cert_binary = ssock.getpeercert(binary_form=True)

            if cert:
                # Subject Common Name
                subject = cert.get("subject", ())
                for rdn in subject:
                    for attr, value in rdn:  # type: ignore[misc]
                        if attr == "commonName":
                            result["ssl_subject_cn"] = value
                            break

                # Issuer organization and CN
                issuer = cert.get("issuer", ())
                for rdn in issuer:
                    for attr, value in rdn:  # type: ignore[misc]
                        if attr == "organizationName":
                            result["ssl_issuer"] = value
                        elif attr == "commonName":
                            result["ssl_issuer_cn"] = value

                # Validity dates
                not_after = cert.get("notAfter")
                if not_after and isinstance(not_after, str):
                    result["ssl_expires"] = ssl.cert_time_to_seconds(not_after)

                not_before = cert.get("notBefore")
                if not_before and isinstance(not_before, str):
                    result["ssl_not_before"] = ssl.cert_time_to_seconds(not_before)

                # Subject Alternative Names
                san_list: list[str] = []
                for san_type, san_value in cert.get("subjectAltName", ()):  # type: ignore[misc]
                    if san_type == "DNS" and isinstance(san_value, str):
                        san_list.append(san_value)
                if san_list:
                    result["ssl_san"] = san_list

                # Serial number
                serial = cert.get("serialNumber")
                if serial:
                    result["ssl_serial"] = serial

                # Version
                version = cert.get("version")
                if version is not None:
                    result["ssl_version"] = version

            # SHA-256 fingerprint from binary cert
            if cert_binary:
                fingerprint = hashlib.sha256(cert_binary).hexdigest().upper()
                # Format as colon-separated pairs
                formatted = ":".join(fingerprint[i : i + 2] for i in range(0, len(fingerprint), 2))
                result["ssl_fingerprint"] = f"SHA256:{formatted}"

            # TLS protocol and cipher
            protocol = ssock.version()
            if protocol:
                result["ssl_protocol"] = protocol

            cipher_info = ssock.cipher()
            if cipher_info:
                result["ssl_cipher"] = cipher_info[0]
                result["ssl_cipher_bits"] = cipher_info[2]

        # Validate certificate separately (check expiry, trust chain, hostname)
        result["ssl_valid"] = False
        try:
            verify_context = ssl.create_default_context()
            with (
                socket.create_connection((host, port), timeout=timeout) as sock2,
                verify_context.wrap_socket(sock2, server_hostname=host),
            ):
                # If we get here, certificate is valid
                result["ssl_valid"] = True
        except ssl.SSLError:
            # Certificate validation failed (expired, untrusted, hostname mismatch)
            pass

        return result

    @classmethod
    async def _test_geo(
        cls,
        relay: Relay,
        ip: str | None,
        city_reader: geoip2.database.Reader | None,
        asn_reader: geoip2.database.Reader | None = None,
    ) -> Metadata:
        """Lookup geolocation for relay using provided IP.

        Note: Geolocation lookup uses local GeoIP database, no network call.
        Only works for clearnet relays (overlay networks have no public IP).
        """
        data: dict[str, Any] = {}

        if relay.network != "clearnet" or not city_reader or not ip:
            return Metadata(data)

        try:
            data = await asyncio.to_thread(cls._lookup_geo_sync, ip, city_reader, asn_reader)
            if len(data) <= 1:  # Only geo_ip, no actual geo data
                data = {}
        except Exception:
            pass

        return Metadata(data)

    @staticmethod
    def _lookup_geo_sync(
        ip: str,
        city_reader: geoip2.database.Reader,
        asn_reader: geoip2.database.Reader | None = None,
    ) -> dict[str, Any]:
        """Synchronous geolocation lookup with comprehensive field extraction."""
        result: dict[str, Any] = {"geo_ip": ip}

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

        # ASN data
        if asn_reader:
            try:
                asn_response = asn_reader.asn(ip)
                if asn_response.autonomous_system_number:
                    result["geo_asn"] = asn_response.autonomous_system_number
                if asn_response.autonomous_system_organization:
                    result["geo_asn_org"] = asn_response.autonomous_system_organization
                if asn_response.network:
                    result["geo_network"] = str(asn_response.network)
            except Exception:
                pass

        return result

    @classmethod
    async def _test_dns(
        cls,
        relay: Relay,
        timeout: float,
    ) -> Metadata:
        """Resolve DNS records for relay.

        Note: DNS resolution uses system resolver, no proxy support.
        Only works for clearnet relays (overlay hostnames can't be resolved).
        """
        data: dict[str, Any] = {}

        if relay.network != "clearnet":
            return Metadata(data)

        try:
            data = await asyncio.to_thread(cls._resolve_dns_sync, relay.host, timeout)
        except Exception:
            pass

        return Metadata(data)

    @staticmethod
    def _resolve_dns_sync(host: str, timeout: float) -> dict[str, Any]:
        """Synchronous comprehensive DNS resolution."""
        result: dict[str, Any] = {}
        resolver = dns.resolver.Resolver()
        resolver.timeout = timeout
        resolver.lifetime = timeout

        # A records (IPv4)
        start = perf_counter()
        try:
            answers = resolver.resolve(host, "A")
            ips = [rdata.address for rdata in answers]
            if ips:
                result["dns_ip"] = ips[0]
                result["dns_ips"] = ips
                result["dns_ttl"] = answers.rrset.ttl if answers.rrset else None
            result["dns_rtt"] = int((perf_counter() - start) * 1000)
        except Exception:
            pass

        # AAAA records (IPv6)
        try:
            answers = resolver.resolve(host, "AAAA")
            ips_v6 = [rdata.address for rdata in answers]
            if ips_v6:
                result["dns_ipv6"] = ips_v6[0]
                result["dns_ips_v6"] = ips_v6
        except Exception:
            pass

        # CNAME record
        try:
            answers = resolver.resolve(host, "CNAME")
            for rdata in answers:
                result["dns_cname"] = str(rdata.target).rstrip(".")
                break
        except Exception:
            pass

        # NS records (for the domain, not the host)
        try:
            # Extract domain from host (e.g., relay.example.com -> example.com)
            parts = host.split(".")
            if len(parts) >= 2:
                domain = ".".join(parts[-2:])
                answers = resolver.resolve(domain, "NS")
                ns_list = [str(rdata.target).rstrip(".") for rdata in answers]
                if ns_list:
                    result["dns_ns"] = ns_list
        except Exception:
            pass

        # Reverse DNS (PTR)
        if result.get("dns_ip"):
            try:
                # Convert IP to reverse DNS format
                ip = result["dns_ip"]
                reverse_name = dns.reversename.from_address(ip)
                answers = resolver.resolve(reverse_name, "PTR")
                for rdata in answers:
                    result["dns_reverse"] = str(rdata.target).rstrip(".")
                    break
            except Exception:
                pass

        return result

    @classmethod
    async def _test_http(
        cls,
        relay: Relay,
        timeout: float,
        proxy_url: str | None = None,
    ) -> Metadata:
        """Extract HTTP headers from WebSocket upgrade.

        Args:
            relay: Relay to test
            timeout: Request timeout in seconds
            proxy_url: Optional SOCKS5 proxy URL for overlay networks

        Note: For clearnet relays without proxy, uses sync http.client.
        For overlay networks or when proxy is specified, uses aiohttp with proxy.
        """
        data: dict[str, Any] = {}

        # Use async aiohttp when proxy is needed
        if proxy_url:
            try:
                data = await cls._check_http_async(relay, timeout, proxy_url)
            except Exception:
                pass
            return Metadata(data)

        # Skip non-clearnet relays without proxy
        if relay.network != "clearnet":
            return Metadata(data)

        # Use sync http.client for clearnet (faster, no extra dependencies)
        try:
            data = await asyncio.to_thread(cls._check_http_sync, relay, timeout)
        except Exception:
            pass

        return Metadata(data)

    @classmethod
    async def _check_http_async(
        cls,
        relay: Relay,
        timeout: float,
        proxy_url: str,
    ) -> dict[str, Any]:
        """Async HTTP header extraction via aiohttp with proxy support.

        SSL verification is disabled to allow testing relays with expired
        or invalid certificates (SSL validation is done separately in _test_ssl).
        """
        import aiohttp
        from aiohttp_socks import ProxyConnector

        result: dict[str, Any] = {}

        # Build URL for HTTP request (convert ws:// to http://, wss:// to https://)
        scheme = "https" if relay.scheme == "wss" else "http"
        port = relay.port or (443 if relay.scheme == "wss" else 80)
        path = relay.path or "/"
        url = f"{scheme}://{relay.host}:{port}{path}"

        # WebSocket upgrade headers
        headers = {
            "Host": relay.host,
            "Upgrade": "websocket",
            "Connection": "Upgrade",
            "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
            "Sec-WebSocket-Version": "13",
        }

        # Disable SSL verification
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        connector = ProxyConnector.from_url(proxy_url, ssl=ssl_context)
        client_timeout = aiohttp.ClientTimeout(total=timeout)

        async with (
            aiohttp.ClientSession(connector=connector, timeout=client_timeout) as session,
            session.get(url, headers=headers) as response,
        ):
            server = response.headers.get("Server")
            if server:
                result["http_server"] = server

            powered_by = response.headers.get("X-Powered-By")
            if powered_by:
                result["http_powered_by"] = powered_by

        return result

    @staticmethod
    def _check_http_sync(relay: Relay, timeout: float) -> dict[str, Any]:
        """Synchronous HTTP header extraction via WebSocket upgrade request.

        SSL verification is disabled to allow testing relays with expired
        or invalid certificates (SSL validation is done separately in _test_ssl).
        """
        import http.client

        result: dict[str, Any] = {}

        port = relay.port or (443 if relay.scheme == "wss" else 80)
        path = relay.path or "/"

        conn: http.client.HTTPConnection | http.client.HTTPSConnection
        if relay.scheme == "wss":
            # Disable SSL verification
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            conn = http.client.HTTPSConnection(
                relay.host, port, timeout=timeout, context=ssl_context
            )
        else:
            conn = http.client.HTTPConnection(relay.host, port, timeout=timeout)

        try:
            # Send WebSocket upgrade request
            headers = {
                "Host": relay.host,
                "Upgrade": "websocket",
                "Connection": "Upgrade",
                "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
                "Sec-WebSocket-Version": "13",
            }
            conn.request("GET", path, headers=headers)
            response = conn.getresponse()

            # Extract relevant headers
            server = response.getheader("Server")
            if server:
                result["http_server"] = server

            powered_by = response.getheader("X-Powered-By")
            if powered_by:
                result["http_powered_by"] = powered_by

        finally:
            conn.close()

        return result

    # --- Factory method ---

    def to_relay_metadata(
        self,
    ) -> tuple[
        RelayMetadata | None,
        RelayMetadata | None,
        RelayMetadata | None,
        RelayMetadata | None,
        RelayMetadata | None,
    ]:
        """
        Convert to RelayMetadata objects for database storage.

        Returns:
            Tuple of (rtt, ssl, geo, dns, http) where each is RelayMetadata or None.
        """
        from .relay_metadata import MetadataType, RelayMetadata

        def make(metadata: Metadata | None, metadata_type: MetadataType) -> RelayMetadata | None:
            if metadata is None:
                return None
            return RelayMetadata(
                relay=self.relay,
                metadata=metadata,
                metadata_type=metadata_type,
                generated_at=self.generated_at,
            )

        return (
            make(self.rtt_metadata, MetadataType.NIP66_RTT),
            make(self.ssl_metadata, MetadataType.NIP66_SSL),
            make(self.geo_metadata, MetadataType.NIP66_GEO),
            make(self.dns_metadata, MetadataType.NIP66_DNS),
            make(self.http_metadata, MetadataType.NIP66_HTTP),
        )

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
        run_dns: bool = True,
        run_http: bool = True,
        proxy_url: str | None = None,
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
            run_geo: Run geolocation test. Requires city_reader and dns_ip.
            run_dns: Run DNS resolution test (clearnet only)
            run_http: Run HTTP headers test (clearnet only, or via proxy for overlay)
            proxy_url: Optional SOCKS5 proxy URL for overlay networks (Tor, I2P, Loki)

        Returns:
            Nip66 instance with test results

        Raises:
            Nip66TestError: If all tests fail and no metadata collected
            ValueError: If run_rtt=True but keys/event_builder not provided
        """
        if run_rtt and (keys is None or event_builder is None):
            raise ValueError("run_rtt=True requires keys and event_builder")

        timeout = timeout if timeout is not None else cls._DEFAULT_TEST_TIMEOUT

        # Phase 1: Run DNS first (needed for geo lookup)
        dns_metadata: Metadata | None = None
        dns_ip: str | None = None
        if run_dns:
            dns_metadata = await cls._test_dns(relay, timeout)
            if dns_metadata and dns_metadata.data:
                dns_ip = dns_metadata.data.get("dns_ip")

        # Phase 2: Run remaining tests in parallel
        tasks: list[Any] = []
        task_names: list[str] = []

        if run_rtt and keys and event_builder:
            tasks.append(cls._test_rtt(relay, timeout, keys, event_builder, proxy_url))
            task_names.append("rtt")
        if run_ssl:
            tasks.append(cls._test_ssl(relay, timeout))
            task_names.append("ssl")
        if run_geo:
            tasks.append(cls._test_geo(relay, dns_ip, city_reader, asn_reader))
            task_names.append("geo")
        if run_http:
            tasks.append(cls._test_http(relay, timeout, proxy_url))
            task_names.append("http")

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Map results back to metadata types
        rtt_metadata: Metadata | None = None
        ssl_metadata: Metadata | None = None
        geo_metadata: Metadata | None = None
        http_metadata: Metadata | None = None

        for name, result in zip(task_names, results, strict=True):
            if isinstance(result, BaseException):
                continue
            if name == "rtt":
                rtt_metadata = result
            elif name == "ssl":
                ssl_metadata = result
            elif name == "geo":
                geo_metadata = result
            elif name == "http":
                http_metadata = result

        try:
            return cls(
                relay=relay,
                rtt_metadata=rtt_metadata,
                ssl_metadata=ssl_metadata,
                geo_metadata=geo_metadata,
                dns_metadata=dns_metadata,
                http_metadata=http_metadata,
            )
        except ValueError as e:
            raise Nip66TestError(relay, e) from e
