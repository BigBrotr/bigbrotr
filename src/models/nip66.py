"""
NIP-66 Relay Monitoring and Discovery.

This module provides the Nip66 class for testing relay capabilities and collecting
monitoring data per NIP-66 specification. Tests relay connectivity (open, read, write),
collects SSL certificate info, DNS records, HTTP headers, network info, and performs
geolocation lookup.

See: https://github.com/nostr-protocol/nips/blob/master/66.md

Complete NIP-66 metadata structures::

    # RTT (Round-Trip Time) metadata - optional, present if any test succeeded
    rtt_metadata = {
        "rtt_open": 150,  # Connection time in ms
        "rtt_read": 200,  # Read test time in ms
        "rtt_write": 180,  # Write test time in ms
    }

    # Probe metadata - optional, present if probe test was performed
    probe_metadata = {
        "probe_open_success": True,  # True if connection succeeded
        "probe_open_reason": None,  # Raw error message (only if probe_open_success=False)
        "probe_read_success": True,  # True if read worked without restrictions
        "probe_read_reason": None,  # Raw rejection message (only if probe_read_success=False)
        "probe_write_success": False,  # True if write worked without restrictions
        "probe_write_reason": "auth-required: please authenticate",  # Raw rejection message
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

    # Geo metadata - optional, requires GeoIP City database
    geo_metadata = {
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
        "geohash": "9q8yyk8yu",  # NIP-52 geohash (9 chars precision)
        "geo_geoname_id": 5391959,  # GeoNames ID
    }

    # Net metadata - optional, requires GeoIP ASN database
    net_metadata = {
        "net_ip": "1.2.3.4",  # Resolved IPv4 address
        "net_ipv6": "2606:4700::1",  # Resolved IPv6 address (if available)
        "net_asn": 13335,  # Autonomous System Number
        "net_asn_org": "Cloudflare",  # ASN organization name
        "net_network": "1.2.3.0/24",  # IPv4 network CIDR
        "net_network_v6": "2606:4700::/32",  # IPv6 network CIDR (if available)
    }

    # DNS metadata - optional, clearnet only
    dns_metadata = {
        "dns_ips": ["1.2.3.4", "1.2.3.5"],  # All A record IPs
        "dns_ips_v6": ["2606:4700::1"],  # All AAAA record IPs
        "dns_cname": "proxy.example.com",  # CNAME if present
        "dns_reverse": "server1.example.com",  # Reverse DNS (PTR)
        "dns_ns": ["ns1.cloudflare.com"],  # Nameservers
        "dns_ttl": 300,  # TTL in seconds
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
    read_filter = Filter().limit(1)

    nip66 = await Nip66.test(
        relay,
        keys=keys,
        event_builder=event_builder,
        read_filter=read_filter,
        city_reader=city_reader,
        asn_reader=asn_reader,
    )

    # Probe results via metadata dicts
    if nip66.rtt_metadata:
        print(f"Open RTT: {nip66.rtt_metadata.data.get('rtt_open')}ms")
    if nip66.probe_metadata:
        print(
            f"Write allowed: {nip66.probe_metadata.data.get('probe_write_success')}"
        )
        if not nip66.probe_metadata.data.get("probe_write_success"):
            print(
                f"Write rejected: {nip66.probe_metadata.data.get('probe_write_reason')}"
            )
    if nip66.geo_metadata:
        print(f"Location: {nip66.geo_metadata.data.get('geo_country')}")
    if nip66.net_metadata:
        print(f"ASN: {nip66.net_metadata.data.get('net_asn')}")

    # Convert for database storage (up to 7 RelayMetadata objects)
    rtt, probe, ssl, geo, net, dns, http = nip66.to_relay_metadata()
"""

from __future__ import annotations

import asyncio
import hashlib
import socket
import ssl
from dataclasses import dataclass, field
from datetime import timedelta
from time import perf_counter, time
from typing import TYPE_CHECKING, Any, ClassVar, NamedTuple, TypedDict

import dns.resolver  # type: ignore[import-not-found]
import geohash2
import geoip2.database  # noqa: TC002 - used at runtime in _lookup_geo_sync
import tldextract
from nostr_sdk import EventBuilder, Filter

from core.logger import Logger
from utils.parsing import parse_typed_dict

from .metadata import Metadata
from .relay import NetworkType, Relay


if TYPE_CHECKING:
    from nostr_sdk import Keys

    from .relay_metadata import RelayMetadata


class Nip66RelayMetadata(NamedTuple):
    """Named tuple for NIP-66 relay metadata results."""

    rtt: RelayMetadata | None
    probe: RelayMetadata | None
    ssl: RelayMetadata | None
    geo: RelayMetadata | None
    net: RelayMetadata | None
    dns: RelayMetadata | None
    http: RelayMetadata | None


logger = Logger("models.nip66")


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


class Nip66ProbeData(TypedDict, total=False):
    """Probe test results metadata per NIP-66.

    Captures raw rejection reasons without assuming specific message formats.
    This allows clients to analyze and classify restrictions as needed.
    """

    probe_open_success: bool  # True if connection succeeded
    # Raw error message (only if probe_open_success=False)
    probe_open_reason: str
    probe_read_success: bool  # True if read worked without restrictions
    # Raw rejection message (only if probe_read_success=False)
    probe_read_reason: str
    probe_write_success: bool  # True if write worked without restrictions
    # Raw rejection message (only if probe_write_success=False)
    probe_write_reason: str


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
    """Geolocation metadata per NIP-66 (geographic data only)."""

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


class Nip66NetData(TypedDict, total=False):
    """Network metadata per NIP-66 (network identifiers)."""

    net_ip: str  # Resolved IPv4 address
    net_ipv6: str  # Resolved IPv6 address (if available)
    net_asn: int  # Autonomous System Number
    net_asn_org: str  # ASN organization name
    net_network: str  # IPv4 network CIDR
    net_network_v6: str  # IPv6 network CIDR (if available)


class Nip66DnsData(TypedDict, total=False):
    """DNS metadata per NIP-66."""

    dns_ips: list[str]  # All A record IPs
    dns_ips_v6: list[str]  # All AAAA record IPs
    dns_cname: str  # CNAME record if present
    dns_reverse: str  # Reverse DNS (PTR record)
    dns_ns: list[str]  # Nameservers
    dns_ttl: int  # TTL in seconds


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
    including round-trip times, probe test restrictions, SSL certificate data,
    DNS records, HTTP headers, network info, and geolocation info. Generates up to
    7 RelayMetadata objects for database storage.

    Attributes:
        relay: The Relay being monitored.
        rtt_metadata: RTT data (optional, present if any test succeeded).
        probe_metadata: Probe test results with raw rejection reasons (optional).
        ssl_metadata: SSL/TLS certificate data (optional, clearnet wss:// only).
        geo_metadata: Geolocation data (optional, requires GeoIP City database).
        net_metadata: Network data (optional, requires GeoIP ASN database).
        dns_metadata: DNS resolution data (optional, clearnet only).
        http_metadata: HTTP headers data (optional, from WebSocket upgrade).
        generated_at: Unix timestamp when monitoring was performed (default: now).

    Probe metadata fields directly via metadata.data dict:
        nip66.rtt_metadata.data.get('rtt_open')
        nip66.probe_metadata.data.get('probe_write_reason')
        nip66.ssl_metadata.data.get('ssl_issuer')
        nip66.geo_metadata.data.get('geo_country')
        nip66.net_metadata.data.get('net_asn')
    """

    relay: Relay
    rtt_metadata: Metadata | None = None
    probe_metadata: Metadata | None = None
    ssl_metadata: Metadata | None = None
    geo_metadata: Metadata | None = None
    net_metadata: Metadata | None = None
    dns_metadata: Metadata | None = None
    http_metadata: Metadata | None = None
    generated_at: int = field(default_factory=lambda: int(time()))

    def __post_init__(self) -> None:
        """Parse and validate all metadata fields.

        Metadata with all None values becomes None.
        Raises ValueError if all metadata are None.
        """
        object.__setattr__(self, "rtt_metadata", self._to_metadata(self.rtt_metadata, Nip66RttData))
        object.__setattr__(
            self, "probe_metadata", self._to_metadata(self.probe_metadata, Nip66ProbeData)
        )
        object.__setattr__(self, "ssl_metadata", self._to_metadata(self.ssl_metadata, Nip66SslData))
        object.__setattr__(self, "geo_metadata", self._to_metadata(self.geo_metadata, Nip66GeoData))
        object.__setattr__(self, "net_metadata", self._to_metadata(self.net_metadata, Nip66NetData))
        object.__setattr__(self, "dns_metadata", self._to_metadata(self.dns_metadata, Nip66DnsData))
        object.__setattr__(
            self, "http_metadata", self._to_metadata(self.http_metadata, Nip66HttpData)
        )

        # Check that at least one metadata has data
        if all(
            m is None
            for m in [
                self.rtt_metadata,
                self.probe_metadata,
                self.ssl_metadata,
                self.geo_metadata,
                self.net_metadata,
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

    # --- Class-level defaults ---
    _DEFAULT_TEST_TIMEOUT: ClassVar[float] = 10.0

    # --- Internal test methods ---

    @classmethod
    async def _test_rtt_and_probe(
        cls,
        relay: Relay,
        timeout: float,
        keys: Keys,
        event_builder: EventBuilder,
        read_filter: Filter,
        proxy_url: str | None = None,
        allow_insecure: bool = True,
    ) -> tuple[Metadata | None, Metadata | None]:
        """Test relay RTT (round-trip times) and probe test.

        Captures raw rejection messages without assuming specific formats.
        This allows clients to analyze and classify restrictions as needed.

        Args:
            relay: Relay to test
            timeout: Connection timeout in seconds
            keys: Keys for signing test events (required)
            event_builder: EventBuilder for write test (required)
            read_filter: Filter for read test (required)
            proxy_url: Optional SOCKS5 proxy URL for overlay networks
            allow_insecure: If True (default), fallback to insecure transport for
                clearnet relays with invalid SSL certificates.

        Returns:
            Tuple of (rtt_metadata, probe_metadata). If connection fails,
            rtt_metadata is None and probe_metadata contains probe_open_success=False.

        Raises:
            Nip66TestError: If proxy url is missing for overlay networks
        """
        from nostr_sdk import RelayUrl

        from utils.transport import connect_relay

        logger.debug("rtt_probe_started", relay=relay.url, timeout_s=timeout, proxy=proxy_url)

        rtt_data: dict[str, Any] = {}
        probe_data: dict[str, Any] = {}
        relay_url = RelayUrl.parse(relay.url)

        # Test open: measure connection time (includes SSL fallback for clearnet)
        logger.debug("rtt_probe_connecting", relay=relay.url)
        try:
            start = perf_counter()
            client = await connect_relay(relay, keys, proxy_url, timeout, allow_insecure)
            rtt_open = int((perf_counter() - start) * 1000)
            rtt_data["rtt_open"] = rtt_open
            probe_data["probe_open_success"] = True
            logger.debug("rtt_probe_open_ok", relay=relay.url, rtt_open_ms=rtt_open)
        except Exception as e:
            # Connection failed - capture raw error message
            probe_data["probe_open_success"] = False
            probe_data["probe_open_reason"] = str(e)
            logger.debug("rtt_probe_open_failed", relay=relay.url, reason=str(e))
            # Return early - can't test read/write without connection
            return Metadata(rtt_data) if rtt_data else None, Metadata(probe_data)

        try:
            # Test read: stream_events to measure time to first event
            try:
                logger.debug("rtt_probe_reading", relay=relay.url)
                start = perf_counter()
                stream = await client.stream_events(read_filter, timeout=timedelta(seconds=timeout))
                first_event = await stream.next()
                if first_event is not None:
                    rtt_read = int((perf_counter() - start) * 1000)
                    rtt_data["rtt_read"] = rtt_read
                    probe_data["probe_read_success"] = True  # Read succeeded
                    logger.debug("rtt_probe_read_ok", relay=relay.url, rtt_read_ms=rtt_read)
                else:
                    # No events returned - zero-trust: cannot verify read works
                    probe_data["probe_read_success"] = False
                    probe_data["probe_read_reason"] = "no events returned"
                    logger.debug("rtt_probe_read_no_events", relay=relay.url)
            except Exception as e:
                # Read failed - capture raw error message
                probe_data["probe_read_success"] = False
                probe_data["probe_read_reason"] = str(e)
                logger.debug("rtt_probe_read_failed", relay=relay.url, reason=str(e))

            # Test write: send event and verify by reading it back
            try:
                logger.debug("rtt_probe_writing", relay=relay.url)
                start = perf_counter()
                output = await asyncio.wait_for(
                    client.send_event_builder(event_builder), timeout=timeout
                )
                rtt_write = int((perf_counter() - start) * 1000)

                # Check if relay rejected the event
                if output and relay_url in output.failed:
                    reason = output.failed.get(relay_url, "unknown")
                    # Capture raw rejection reason without classification
                    probe_data["probe_write_success"] = False
                    probe_data["probe_write_reason"] = str(reason) if reason else "unknown"
                    logger.debug("rtt_probe_write_rejected", relay=relay.url, reason=str(reason))
                elif output and relay_url in output.success:
                    logger.debug(
                        "rtt_probe_write_accepted", relay=relay.url, rtt_write_ms=rtt_write
                    )
                    # Verify by reading back the event
                    event_id = output.id
                    verify_filter = Filter().id(event_id).limit(1)
                    logger.debug(
                        "rtt_probe_write_verifying", relay=relay.url, event_id=str(event_id)
                    )
                    try:
                        stream = await client.stream_events(
                            verify_filter, timeout=timedelta(seconds=timeout)
                        )
                        verify_event = await stream.next()
                        if verify_event is not None:
                            # Event found: write confirmed
                            rtt_data["rtt_write"] = rtt_write
                            # Write succeeded
                            probe_data["probe_write_success"] = True
                            logger.debug("rtt_probe_write_verified", relay=relay.url)
                        else:
                            # Relay responded OK=true but event not retrievable
                            # Zero-trust: cannot verify write actually works
                            probe_data["probe_write_success"] = False
                            probe_data["probe_write_reason"] = (
                                "unverified: accepted but not retrievable"
                            )
                            logger.debug(
                                "rtt_probe_write_unverified",
                                relay=relay.url,
                                reason="event not retrievable",
                            )
                    except Exception as e:
                        # Verify failed - zero-trust: cannot confirm write
                        probe_data["probe_write_success"] = False
                        probe_data["probe_write_reason"] = f"unverified: verify failed ({e})"
                        logger.debug(
                            "rtt_probe_write_unverified",
                            relay=relay.url,
                            reason=f"verify failed: {e}",
                        )
                else:
                    # No response for this relay - zero-trust: cannot verify
                    probe_data["probe_write_success"] = False
                    probe_data["probe_write_reason"] = "no response from relay"
                    logger.debug("rtt_probe_write_no_response", relay=relay.url)
            except Exception as e:
                # Write failed - capture raw error message
                probe_data["probe_write_success"] = False
                probe_data["probe_write_reason"] = str(e)
                logger.debug("rtt_probe_write_failed", relay=relay.url, reason=str(e))

        finally:
            # Cleanup: disconnect client
            try:
                await client.disconnect()
            except Exception:
                pass

        logger.debug(
            "rtt_probe_completed",
            relay=relay.url,
            rtt_keys=list(rtt_data.keys()),
            probe_keys=list(probe_data.keys()),
        )
        return (
            Metadata(rtt_data) if rtt_data else None,
            Metadata(probe_data) if probe_data else None,
        )

    @classmethod
    async def _test_ssl(
        cls,
        relay: Relay,
        timeout: float,
    ) -> Metadata:
        """Test SSL/TLS certificate and connection details.

        Note: SSL test requires direct socket connection, not supported via proxy.
        Only works for clearnet wss:// relays.

        Raises:
            Nip66TestError: If test returns no data (not applicable or failed).
        """
        logger.debug("ssl_testing", relay=relay.url, timeout_s=timeout)

        if relay.network != NetworkType.CLEARNET:
            logger.debug("ssl_skipped", relay=relay.url, reason="non-clearnet")
            raise Nip66TestError(relay, ValueError("SSL test not applicable (non-clearnet)"))

        data: dict[str, Any] = {}
        port = relay.port or Relay._PORT_WSS
        try:
            logger.debug("ssl_checking", host=relay.host, port=port)
            data = await asyncio.to_thread(cls._check_ssl_sync, relay.host, port, timeout)
            logger.debug("ssl_checked", relay=relay.url, valid=data.get("ssl_valid"))
        except Exception as e:
            logger.debug("ssl_error", relay=relay.url, error=str(e))

        if not data:
            logger.debug("ssl_no_data", relay=relay.url)
            raise Nip66TestError(relay, ValueError("SSL test returned no data"))
        return Metadata(data)

    @staticmethod
    def _check_ssl_sync(host: str, port: int, timeout: float) -> dict[str, Any]:
        """Synchronous SSL check with comprehensive certificate extraction.

        Connects without verification to extract certificate data even if
        the certificate is expired, self-signed, or has other issues.
        Then validates the certificate separately to set ssl_valid.
        """
        result: dict[str, Any] = {}
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        try:
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
                    formatted = ":".join(
                        fingerprint[i : i + 2] for i in range(0, len(fingerprint), 2)
                    )
                    result["ssl_fingerprint"] = f"SHA256:{formatted}"

                # TLS protocol and cipher
                protocol = ssock.version()
                if protocol:
                    result["ssl_protocol"] = protocol

                cipher_info = ssock.cipher()
                if cipher_info:
                    result["ssl_cipher"] = cipher_info[0]
                    result["ssl_cipher_bits"] = cipher_info[2]
        except ssl.SSLError as e:
            logger.debug("ssl_cert_extraction_failed", error=str(e))
        except Exception as e:
            logger.debug("ssl_cert_extraction_error", error=str(e))

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
        except Exception as e:
            logger.debug("ssl_validation_error", error=str(e))

        return result

    @classmethod
    async def _test_geo(
        cls,
        relay: Relay,
        city_reader: geoip2.database.Reader,
    ) -> Metadata:
        """Lookup geolocation for relay.

        Resolves the relay hostname to IP independently, then performs GeoIP City lookup.
        Only works for clearnet relays (overlay networks have no public IP).

        Raises:
            Nip66TestError: If test returns no data (not applicable or failed).
        """
        logger.debug("geo_testing", relay=relay.url)

        if relay.network != NetworkType.CLEARNET:
            logger.debug("geo_skipped", relay=relay.url, reason="non-clearnet")
            raise Nip66TestError(relay, ValueError("Geo test not applicable (non-clearnet)"))

        # Resolve hostname to IP (prefer IPv4, fallback to IPv6)
        logger.debug("geo_resolving", host=relay.host)
        ip: str | None = None

        try:
            ip = await asyncio.to_thread(socket.gethostbyname, relay.host)
            logger.debug("geo_resolved_ipv4", ip=ip, relay=relay.url)
        except Exception as e:
            logger.debug("geo_ipv4_failed", relay=relay.url, error=str(e))

        if ip is None:
            try:
                ipv6_result = await asyncio.to_thread(
                    socket.getaddrinfo, relay.host, None, socket.AF_INET6
                )
                if ipv6_result:
                    ip = str(ipv6_result[0][4][0])
                    logger.debug("geo_resolved_ipv6", ip=ip, relay=relay.url)
            except Exception as e:
                logger.debug("geo_ipv6_failed", relay=relay.url, error=str(e))

        data: dict[str, Any] = {}
        if ip:
            try:
                data = await asyncio.to_thread(cls._lookup_geo_sync, ip, city_reader)
                logger.debug("geo_completed", relay=relay.url, country=data.get("geo_country"))
            except Exception as e:
                logger.debug("geo_lookup_failed", relay=relay.url, error=str(e))

        if not data:
            logger.debug("geo_no_data", relay=relay.url)
            raise Nip66TestError(relay, ValueError("Geo test returned no data"))
        return Metadata(data)

    @staticmethod
    def _lookup_geo_sync(
        ip: str,
        city_reader: geoip2.database.Reader,
    ) -> dict[str, Any]:
        """Synchronous geolocation lookup (geographic data only)."""
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
        except Exception:
            pass

        return result

    @classmethod
    async def _test_net(
        cls,
        relay: Relay,
        asn_reader: geoip2.database.Reader,
    ) -> Metadata:
        """Lookup network/ASN info for relay.

        Resolves hostname to IPv4 and IPv6 independently, then performs ASN lookup.
        Only works for clearnet relays (overlay networks have no public IP).

        Raises:
            Nip66TestError: If test returns no data (not applicable or failed).
        """
        logger.debug("net_testing", relay=relay.url)

        if relay.network != NetworkType.CLEARNET:
            logger.debug("net_skipped", relay=relay.url, reason="non-clearnet")
            raise Nip66TestError(relay, ValueError("Net test not applicable (non-clearnet)"))

        # Resolve hostname to IPv4 and IPv6 independently
        logger.debug("net_resolving", host=relay.host)
        ipv4: str | None = None
        ipv6: str | None = None

        try:
            ipv4 = await asyncio.to_thread(socket.gethostbyname, relay.host)
            logger.debug("net_resolved_ipv4", ip=ipv4, relay=relay.url)
        except Exception as e:
            logger.debug("net_ipv4_failed", relay=relay.url, error=str(e))

        try:
            ipv6_result = await asyncio.to_thread(
                socket.getaddrinfo, relay.host, None, socket.AF_INET6
            )
            if ipv6_result:
                ipv6 = str(ipv6_result[0][4][0])
                logger.debug("net_resolved_ipv6", ip=ipv6, relay=relay.url)
        except Exception as e:
            logger.debug("net_ipv6_failed", relay=relay.url, error=str(e))

        # Lookup ASN info if we have at least one IP
        data: dict[str, Any] = {}
        if ipv4 or ipv6:
            data = await asyncio.to_thread(cls._lookup_net_sync, ipv4, ipv6, asn_reader)
            logger.debug("net_completed", relay=relay.url, asn=data.get("net_asn"))

        if not data:
            logger.debug("net_no_data", relay=relay.url)
            raise Nip66TestError(relay, ValueError("Net test returned no data"))
        return Metadata(data)

    @staticmethod
    def _lookup_net_sync(
        ipv4: str | None,
        ipv6: str | None,
        asn_reader: geoip2.database.Reader,
    ) -> dict[str, Any]:
        """Synchronous network/ASN lookup for both IPv4 and IPv6."""
        result: dict[str, Any] = {}

        # Lookup IPv4
        if ipv4:
            result["net_ip"] = ipv4
            try:
                asn_response = asn_reader.asn(ipv4)
                if asn_response.autonomous_system_number:
                    result["net_asn"] = asn_response.autonomous_system_number
                if asn_response.autonomous_system_organization:
                    result["net_asn_org"] = asn_response.autonomous_system_organization
                if asn_response.network:
                    result["net_network"] = str(asn_response.network)
            except Exception:
                pass

        # Lookup IPv6
        if ipv6:
            result["net_ipv6"] = ipv6
            try:
                asn_response = asn_reader.asn(ipv6)
                if asn_response.network:
                    result["net_network_v6"] = str(asn_response.network)
                # Only set ASN from IPv6 if not already set from IPv4
                if "net_asn" not in result:
                    if asn_response.autonomous_system_number:
                        result["net_asn"] = asn_response.autonomous_system_number
                    if asn_response.autonomous_system_organization:
                        result["net_asn_org"] = asn_response.autonomous_system_organization
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

        Raises:
            Nip66TestError: If test returns no data (not applicable or failed).
        """
        logger.debug("dns_testing", relay=relay.url, timeout_s=timeout)

        if relay.network != NetworkType.CLEARNET:
            logger.debug("dns_skipped", relay=relay.url, reason="non-clearnet")
            raise Nip66TestError(relay, ValueError("DNS test not applicable (non-clearnet)"))

        data: dict[str, Any] = {}
        try:
            logger.debug("dns_resolving", host=relay.host)
            data = await asyncio.to_thread(cls._resolve_dns_sync, relay.host, timeout)
            logger.debug("dns_completed", relay=relay.url, ips=data.get("dns_ips"))
        except Exception as e:
            logger.debug("dns_error", relay=relay.url, error=str(e))

        if not data:
            logger.debug("dns_no_data", relay=relay.url)
            raise Nip66TestError(relay, ValueError("DNS test returned no data"))
        return Metadata(data)

    @staticmethod
    def _resolve_dns_sync(host: str, timeout: float) -> dict[str, Any]:
        """Synchronous comprehensive DNS resolution."""
        result: dict[str, Any] = {}
        resolver = dns.resolver.Resolver()
        resolver.timeout = timeout
        resolver.lifetime = timeout

        # A records (IPv4)
        try:
            answers = resolver.resolve(host, "A")
            ips = [rdata.address for rdata in answers]
            if ips:
                result["dns_ips"] = ips
                if answers.rrset:
                    result["dns_ttl"] = answers.rrset.ttl
        except Exception:
            pass

        # AAAA records (IPv6)
        try:
            answers = resolver.resolve(host, "AAAA")
            ips_v6 = [rdata.address for rdata in answers]
            if ips_v6:
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

        # NS records (for the registered domain, not the full host)
        try:
            # Extract registered domain (handles .co.uk, .com.br, etc.)
            ext = tldextract.extract(host)
            if ext.domain and ext.suffix:
                domain = f"{ext.domain}.{ext.suffix}"
                answers = resolver.resolve(domain, "NS")
                ns_list = [str(rdata.target).rstrip(".") for rdata in answers]
                if ns_list:
                    result["dns_ns"] = ns_list
        except Exception:
            pass

        # Reverse DNS (PTR) - uses first IP from dns_ips if available
        if result.get("dns_ips"):
            try:
                ip = result["dns_ips"][0]
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

        Raises:
            Nip66TestError: If test returns no data (not applicable or failed).
        """
        logger.debug("http_testing", relay=relay.url, timeout_s=timeout, proxy=proxy_url)

        # Non-clearnet relays require proxy
        overlay_networks = (NetworkType.TOR, NetworkType.I2P, NetworkType.LOKI)
        if proxy_url is None and relay.network in overlay_networks:
            logger.warning("http_missing_proxy", relay=relay.url)
            raise Nip66TestError(
                relay, ValueError("HTTP test requires proxy url for overlay networks")
            )

        data: dict[str, Any] = {}
        try:
            data = await cls._check_http(relay, timeout, proxy_url)
            logger.debug("http_completed", relay=relay.url, server=data.get("http_server"))
        except Exception as e:
            logger.debug("http_error", relay=relay.url, error=str(e))

        if not data:
            logger.debug("http_no_data", relay=relay.url)
            raise Nip66TestError(relay, ValueError("HTTP test returned no data"))
        return Metadata(data)

    @staticmethod
    async def _check_http(
        relay: Relay,
        timeout: float,
        proxy_url: str | None = None,
    ) -> dict[str, Any]:
        """Async HTTP header extraction via aiohttp.

        SSL verification is disabled to allow testing relays with expired
        or invalid certificates (SSL validation is done separately in _test_ssl).

        Args:
            relay: Relay to test
            timeout: Request timeout in seconds
            proxy_url: Optional SOCKS5 proxy URL (required for overlay networks)
        """
        import aiohttp

        result: dict[str, Any] = {}

        # Build URL for HTTP request (convert ws:// to http://, wss:// to https://)
        scheme = "https" if relay.scheme == "wss" else "http"
        port = relay.port or (Relay._PORT_WSS if relay.scheme == "wss" else Relay._PORT_WS)
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

        # Use proxy connector if proxy_url provided, otherwise standard TCPConnector
        connector: aiohttp.BaseConnector
        if proxy_url:
            from aiohttp_socks import ProxyConnector

            connector = ProxyConnector.from_url(proxy_url, ssl=ssl_context)
        else:
            connector = aiohttp.TCPConnector(ssl=ssl_context)

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

    # --- Factory method ---

    def to_relay_metadata(self) -> Nip66RelayMetadata:
        """
        Convert to RelayMetadata objects for database storage.

        Returns:
            Nip66RelayMetadata named tuple with rtt, probe, ssl, geo, net, dns, http fields.
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

        return Nip66RelayMetadata(
            rtt=make(self.rtt_metadata, MetadataType.NIP66_RTT),
            probe=make(self.probe_metadata, MetadataType.NIP66_PROBE),
            ssl=make(self.ssl_metadata, MetadataType.NIP66_SSL),
            geo=make(self.geo_metadata, MetadataType.NIP66_GEO),
            net=make(self.net_metadata, MetadataType.NIP66_NET),
            dns=make(self.dns_metadata, MetadataType.NIP66_DNS),
            http=make(self.http_metadata, MetadataType.NIP66_HTTP),
        )

    # --- Main test method ---

    @classmethod
    async def test(
        cls,
        relay: Relay,
        timeout: float | None = None,
        keys: Keys | None = None,
        event_builder: EventBuilder | None = None,
        read_filter: Filter | None = None,
        city_reader: geoip2.database.Reader | None = None,
        asn_reader: geoip2.database.Reader | None = None,
        run_rtt: bool = True,
        run_probe: bool = True,
        run_ssl: bool = True,
        run_geo: bool = True,
        run_net: bool = True,
        run_dns: bool = True,
        run_http: bool = True,
        proxy_url: str | None = None,
        allow_insecure: bool = True,
    ) -> Nip66:
        """
        Test relay and collect NIP-66 monitoring data.

        All tests are enabled by default. Disable specific tests with run_* flags.
        At least one test must succeed to create a valid Nip66 instance.

        Note: run_rtt and run_probe share the same WebSocket test internally.
        The test runs if either flag is True; results are kept based on individual flags.

        Args:
            relay: Relay object to test
            timeout: Connection timeout in seconds (default: _DEFAULT_TEST_TIMEOUT)
            keys: Keys for signing test events (required if run_rtt or run_probe)
            event_builder: EventBuilder for write test (required if run_rtt or run_probe)
            read_filter: Filter for read test (required if run_rtt or run_probe)
            city_reader: Pre-opened GeoLite2-City database reader (required if run_geo=True)
            asn_reader: Pre-opened GeoLite2-ASN database reader (required if run_net=True)
            run_rtt: Collect RTT timing data (rtt_open, rtt_read, rtt_write in ms).
            run_probe: Collect probe status data (is_open, is_read, is_write booleans).
            run_ssl: Run SSL certificate test (clearnet wss:// only)
            run_geo: Run geolocation test. Requires city_reader.
            run_net: Run network/ASN test. Requires asn_reader.
            run_dns: Run DNS resolution test (clearnet only)
            run_http: Run HTTP headers test (clearnet only, or via proxy for overlay)
            proxy_url: Optional SOCKS5 proxy URL for overlay networks (Tor, I2P, Loki)
            allow_insecure: If True (default), fallback to insecure transport for
                clearnet relays with invalid SSL certificates.

        Returns:
            Nip66 instance with test results

        Raises:
            Nip66TestError: If all tests fail and no metadata collected
        """
        timeout = timeout if timeout is not None else cls._DEFAULT_TEST_TIMEOUT
        logger.debug("test_started", relay=relay.url, timeout_s=timeout)

        # Run all tests in parallel (each test is independent)
        tasks: list[Any] = []
        task_names: list[str] = []

        if (
            (run_rtt or run_probe)
            and keys is not None
            and event_builder is not None
            and read_filter is not None
        ):
            tasks.append(
                cls._test_rtt_and_probe(
                    relay, timeout, keys, event_builder, read_filter, proxy_url, allow_insecure
                )
            )
            task_names.append("rtt_and_probe")

        if run_ssl:
            tasks.append(cls._test_ssl(relay, timeout))
            task_names.append("ssl")

        if run_geo and city_reader is not None:
            tasks.append(cls._test_geo(relay, city_reader))
            task_names.append("geo")

        if run_net and asn_reader is not None:
            tasks.append(cls._test_net(relay, asn_reader))
            task_names.append("net")

        if run_dns:
            tasks.append(cls._test_dns(relay, timeout))
            task_names.append("dns")

        if run_http:
            tasks.append(cls._test_http(relay, timeout, proxy_url))
            task_names.append("http")

        logger.debug("test_running", tests=task_names)
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Map results back to metadata types
        rtt_metadata: Metadata | None = None
        probe_metadata: Metadata | None = None
        ssl_metadata: Metadata | None = None
        geo_metadata: Metadata | None = None
        net_metadata: Metadata | None = None
        dns_metadata: Metadata | None = None
        http_metadata: Metadata | None = None

        for name, result in zip(task_names, results, strict=True):
            if isinstance(result, BaseException):
                logger.debug("test_task_failed", test=name, error=str(result))
                continue
            logger.debug("test_task_succeeded", test=name)
            if name == "rtt_and_probe":
                _rtt, _probe = result
                if run_rtt:
                    rtt_metadata = _rtt
                if run_probe:
                    probe_metadata = _probe
            elif name == "ssl":
                ssl_metadata = result
            elif name == "geo":
                geo_metadata = result
            elif name == "net":
                net_metadata = result
            elif name == "dns":
                dns_metadata = result
            elif name == "http":
                http_metadata = result

        try:
            nip66 = cls(
                relay=relay,
                rtt_metadata=rtt_metadata,
                probe_metadata=probe_metadata,
                ssl_metadata=ssl_metadata,
                geo_metadata=geo_metadata,
                net_metadata=net_metadata,
                dns_metadata=dns_metadata,
                http_metadata=http_metadata,
            )
            logger.debug("test_completed", relay=relay.url)
            return nip66
        except ValueError as e:
            logger.warning("test_all_failed", relay=relay.url)
            raise Nip66TestError(relay, e) from e
