#!/usr/bin/env python3
"""
Test NIP-66 Relay Monitoring

Interactive script for testing the `Nip66` model:
- RTT - Round-trip time tests (open, read, write) using Client wrapper
- SSL - Certificate checks (clearnet only)
- GEO - Geolocation lookup (clearnet only)
- DNS - DNS resolution (clearnet only)
- HTTP - HTTP headers (clearnet or via proxy)
- Proxy support - For Tor/I2P/Loki relays (RTT and HTTP tests only)

Usage:
    python notebooks/test_nip66.py
    python notebooks/test_nip66.py --relay wss://relay.damus.io
    python notebooks/test_nip66.py --onion --proxy socks5://127.0.0.1:9050

Requirements:
    - GeoIP databases in implementations/bigbrotr/static/
    - Tor proxy for .onion relays (default: socks5://127.0.0.1:9050)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path


# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import geoip2.database
from nostr_sdk import EventBuilder, Filter, Kind

from models.keys import Keys
from models.metadata import Metadata
from models.nip66 import Nip66, Nip66TestError
from models.relay import Relay


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

DEFAULT_RELAY = "wss://relay.damus.io"
BAD_SSL_RELAY = "wss://relay.nostr.band"
ONION_RELAY = "ws://oxtrdevav64z64yb7x6rjg4ntzqjhedm5b5zjqulugknhzr46ny2qbad.onion"
TOR_PROXY = "socks5://127.0.0.1:9050"

GEOIP_DIR = Path(__file__).parent.parent / "implementations/bigbrotr/static"


# -----------------------------------------------------------------------------
# Setup
# -----------------------------------------------------------------------------


def setup_logging(debug: bool = False) -> None:
    """Configure logging for nip66 and client modules."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("models.nip66").setLevel(level)
    logging.getLogger("models.client").setLevel(level)
    logging.getLogger("nostr_sdk").setLevel(logging.WARNING)


def load_geoip_readers() -> tuple[geoip2.database.Reader | None, geoip2.database.Reader | None]:
    """Load GeoIP database readers."""
    city_path = GEOIP_DIR / "GeoLite2-City.mmdb"
    asn_path = GEOIP_DIR / "GeoLite2-ASN.mmdb"

    city_reader = geoip2.database.Reader(str(city_path)) if city_path.exists() else None
    asn_reader = geoip2.database.Reader(str(asn_path)) if asn_path.exists() else None

    return city_reader, asn_reader


def print_separator(title: str) -> None:
    """Print a section separator."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print("=" * 60)


# -----------------------------------------------------------------------------
# Test Functions
# -----------------------------------------------------------------------------


async def test_full_relay(
    relay_url: str,
    keys: Keys,
    event_builder: EventBuilder,
    read_filter: Filter,
    city_reader: geoip2.database.Reader | None,
    asn_reader: geoip2.database.Reader | None,
    proxy_url: str | None = None,
    timeout: float = 10.0,
) -> Nip66 | None:
    """Run full NIP-66 test on a relay."""
    relay = Relay(relay_url)
    print_separator(f"Full Test: {relay.url}")
    print(f"Network: {relay.network}")
    if proxy_url:
        print(f"Proxy: {proxy_url}")

    try:
        nip66 = await Nip66.test(
            relay,
            keys=keys,
            event_builder=event_builder,
            read_filter=read_filter,
            city_reader=city_reader,
            asn_reader=asn_reader,
            proxy_url=proxy_url,
            timeout=timeout,
        )

        print("\nMetadata collected:")
        print(f"  RTT:  {nip66.rtt_metadata is not None}")
        print(f"  SSL:  {nip66.ssl_metadata is not None}")
        print(f"  GEO:  {nip66.geo_metadata is not None}")
        print(f"  DNS:  {nip66.dns_metadata is not None}")
        print(f"  HTTP: {nip66.http_metadata is not None}")

        return nip66

    except Nip66TestError as e:
        print(f"\nTest failed: {e}")
        return None


def print_rtt_results(nip66: Nip66) -> None:
    """Print RTT test results."""
    print_separator("RTT Results")
    if nip66.rtt_metadata:
        rtt = nip66.rtt_metadata.data
        print(f"rtt_open:  {rtt.get('rtt_open')} ms")
        print(f"rtt_read:  {rtt.get('rtt_read')} ms")
        print(f"rtt_write: {rtt.get('rtt_write')} ms")
    else:
        print("No RTT data collected")


def print_ssl_results(nip66: Nip66) -> None:
    """Print SSL test results."""
    print_separator("SSL Results")
    if nip66.ssl_metadata:
        ssl = nip66.ssl_metadata.data
        print(f"ssl_valid:      {ssl.get('ssl_valid')}")
        print(f"ssl_subject_cn: {ssl.get('ssl_subject_cn')}")
        print(f"ssl_issuer:     {ssl.get('ssl_issuer')}")
        print(f"ssl_protocol:   {ssl.get('ssl_protocol')}")
        print(f"ssl_cipher:     {ssl.get('ssl_cipher')}")
    else:
        print("No SSL data (overlay relay or ws://)")


def print_geo_results(nip66: Nip66) -> None:
    """Print GEO test results."""
    print_separator("GEO Results")
    if nip66.geo_metadata:
        geo = nip66.geo_metadata.data
        print(f"geo_ip:      {geo.get('geo_ip')}")
        print(f"geo_country: {geo.get('geo_country')}")
        print(f"geo_city:    {geo.get('geo_city')}")
        print(f"geo_asn:     {geo.get('geo_asn')}")
        print(f"geo_asn_org: {geo.get('geo_asn_org')}")
    else:
        print("No GEO data (overlay relay or no GeoIP DB)")


def print_dns_results(nip66: Nip66) -> None:
    """Print DNS test results."""
    print_separator("DNS Results")
    if nip66.dns_metadata:
        dns = nip66.dns_metadata.data
        print(f"dns_ip:   {dns.get('dns_ip')}")
        print(f"dns_ipv6: {dns.get('dns_ipv6')}")
        print(f"dns_ns:   {dns.get('dns_ns')}")
        print(f"dns_ttl:  {dns.get('dns_ttl')} seconds")
        print(f"dns_rtt:  {dns.get('dns_rtt')} ms")
    else:
        print("No DNS data (overlay relay)")


def print_http_results(nip66: Nip66) -> None:
    """Print HTTP test results."""
    print_separator("HTTP Results")
    if nip66.http_metadata:
        http = nip66.http_metadata.data
        print(f"http_server:     {http.get('http_server')}")
        print(f"http_powered_by: {http.get('http_powered_by')}")
    else:
        print("No HTTP data")


def print_full_json(nip66: Nip66) -> None:
    """Print full JSON output."""
    print_separator("Full JSON Output")
    full_data = {
        "relay_url": nip66.relay.url,
        "generated_at": nip66.generated_at,
        "rtt": nip66.rtt_metadata.data if nip66.rtt_metadata else None,
        "ssl": nip66.ssl_metadata.data if nip66.ssl_metadata else None,
        "geo": nip66.geo_metadata.data if nip66.geo_metadata else None,
        "dns": nip66.dns_metadata.data if nip66.dns_metadata else None,
        "http": nip66.http_metadata.data if nip66.http_metadata else None,
    }
    print(json.dumps(full_data, indent=2))


async def test_bad_ssl_relay(
    keys: Keys,
    event_builder: EventBuilder,
    read_filter: Filter,
    city_reader: geoip2.database.Reader | None,
    asn_reader: geoip2.database.Reader | None,
) -> None:
    """
    Test relay.nostr.band which has invalid SSL certificate.

    Client wrapper will:
    1. Try secure TLS first
    2. Get SSLError (certificate for realsearch.cc, not relay.nostr.band)
    3. Fallback to insecure TLS
    """
    print_separator(f"Bad SSL Test: {BAD_SSL_RELAY}")
    print("This relay has certificate mismatch (presents cert for realsearch.cc)")
    print("Client wrapper will fallback to insecure TLS")

    relay = Relay(BAD_SSL_RELAY)
    print(f"\nNetwork: {relay.network}")

    try:
        result = await Nip66.test(
            relay,
            keys=keys,
            event_builder=EventBuilder.text_note("SmartTransport test"),
            read_filter=Filter().limit(1),
            city_reader=city_reader,
            asn_reader=asn_reader,
            timeout=15.0,
        )

        print("\nMetadata collected:")
        print(f"  RTT:  {result.rtt_metadata is not None}")
        if result.rtt_metadata:
            rtt = result.rtt_metadata.data
            print(f"        rtt_open={rtt.get('rtt_open')}ms")
            print(f"        rtt_read={rtt.get('rtt_read')}ms")
            print(f"        rtt_write={rtt.get('rtt_write')}ms")
        print(f"  SSL:  {result.ssl_metadata is not None}")
        if result.ssl_metadata:
            ssl_data = result.ssl_metadata.data
            print(f"        ssl_valid={ssl_data.get('ssl_valid')} (expected: False)")

    except Nip66TestError as e:
        print(f"\nTest failed: {e}")


async def test_onion_relay(
    keys: Keys,
    event_builder: EventBuilder,
    read_filter: Filter,
    proxy_url: str,
) -> None:
    """Test Tor relay via SOCKS5 proxy."""
    print_separator(f"Tor Relay Test: {ONION_RELAY}")
    print(f"Proxy: {proxy_url}")
    print("\nNote: .onion relays use ws:// (no TLS over Tor)")
    print("Only RTT and HTTP tests use the proxy")

    relay = Relay(ONION_RELAY)
    print(f"Network: {relay.network}")

    try:
        nip66 = await Nip66.test(
            relay,
            keys=keys,
            event_builder=EventBuilder.text_note("Tor relay test"),
            read_filter=Filter().limit(1),
            proxy_url=proxy_url,
            timeout=30.0,  # Tor is slower
        )

        print("\nResults:")
        print(f"  RTT:  {nip66.rtt_metadata is not None}")
        if nip66.rtt_metadata:
            rtt = nip66.rtt_metadata.data
            print(f"        rtt_open={rtt.get('rtt_open')}ms")
            print(f"        rtt_read={rtt.get('rtt_read')}ms")
            print(f"        rtt_write={rtt.get('rtt_write')}ms")
        print(f"  HTTP: {nip66.http_metadata is not None}")
        if nip66.http_metadata:
            print(f"        server={nip66.http_metadata.data.get('http_server')}")
        print(f"  SSL:  {nip66.ssl_metadata is not None} (expected: False - not for .onion)")
        print(f"  DNS:  {nip66.dns_metadata is not None} (expected: False - not for .onion)")
        print(f"  GEO:  {nip66.geo_metadata is not None} (expected: False - not for .onion)")

    except Nip66TestError as e:
        print(f"\nTest failed: {e}")
        print(f"Error: {e.error}")
        print("\nMake sure Tor proxy is running:")
        print("  docker run -d -p 9050:9050 dperson/torproxy")


async def test_selective(relay: Relay) -> None:
    """Test selective test execution with run_* flags."""
    print_separator("Selective Tests")

    # SSL only
    print("\n--- SSL Only ---")
    try:
        nip66_ssl = await Nip66.test(
            relay,
            run_rtt=False,
            run_geo=False,
            run_dns=False,
            run_http=False,
        )
        if nip66_ssl.ssl_metadata:
            print(f"Protocol: {nip66_ssl.ssl_metadata.data.get('ssl_protocol')}")
    except Nip66TestError as e:
        print(f"SSL test failed: {e}")

    # DNS only
    print("\n--- DNS Only ---")
    try:
        nip66_dns = await Nip66.test(
            relay,
            run_rtt=False,
            run_ssl=False,
            run_geo=False,
            run_http=False,
        )
        if nip66_dns.dns_metadata:
            print(f"DNS IP: {nip66_dns.dns_metadata.data.get('dns_ip')}")
    except Nip66TestError as e:
        print(f"DNS test failed: {e}")


async def test_error_handling(relay: Relay) -> None:
    """Test error handling scenarios."""
    print_separator("Error Handling")

    # Missing required parameters for RTT
    print("\n--- Missing Parameters (RTT without keys) ---")
    try:
        await Nip66.test(
            relay,
            run_rtt=True,
            run_ssl=False,
            run_geo=False,
            run_dns=False,
            run_http=False,
        )
    except Nip66TestError as e:
        print(f"Correctly raised: {e}")

    # Empty metadata
    print("\n--- Empty Metadata ---")
    try:
        Nip66(
            relay=relay,
            rtt_metadata=Metadata({}),
            ssl_metadata=Metadata({}),
            geo_metadata=Metadata({}),
            dns_metadata=Metadata({}),
            http_metadata=Metadata({}),
        )
    except ValueError as e:
        print(f"Correctly raised: {e}")


def print_summary() -> None:
    """Print summary information."""
    print_separator("Summary")
    print("""
Key Points:
- RTT tests use models.Client wrapper with automatic TLS fallback
- Clearnet: SSL fallback via _SmartWebSocketTransport
- Overlay (tor/i2p/loki): proxy via ConnectionMode.PROXY
- Access fields via nip66.<type>_metadata.data["key"]
- At least one metadata type must have data
- RTT test requires: keys, event_builder, read_filter
- Only RTT and HTTP tests use proxy_url

Client Behavior:
┌─────────────────────────────────────┬────────────────────────────────────┐
│ Network                             │ Transport                          │
├─────────────────────────────────────┼────────────────────────────────────┤
│ Clearnet (wss://)                   │ _SmartWebSocketTransport           │
│ Overlay (tor/i2p/loki)              │ ConnectionMode.PROXY               │
└─────────────────────────────────────┴────────────────────────────────────┘

Metadata Types:
┌──────┬─────────────────────────────────────┬───────────────┐
│ Type │ Fields                              │ Proxy Support │
├──────┼─────────────────────────────────────┼───────────────┤
│ RTT  │ rtt_open, rtt_read, rtt_write       │ Yes           │
│ HTTP │ http_server, http_powered_by        │ Yes           │
│ SSL  │ ssl_valid, ssl_protocol, ...        │ No (clearnet) │
│ DNS  │ dns_ip, dns_ipv6, dns_ns, ...       │ No (clearnet) │
│ GEO  │ geo_country, geo_city, geo_asn, ... │ No (clearnet) │
└──────┴─────────────────────────────────────┴───────────────┘
""")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------


async def main() -> None:
    """Run NIP-66 tests."""
    parser = argparse.ArgumentParser(description="Test NIP-66 relay monitoring")
    parser.add_argument("--relay", default=DEFAULT_RELAY, help="Relay URL to test")
    parser.add_argument("--proxy", default=TOR_PROXY, help="SOCKS5 proxy URL")
    parser.add_argument("--timeout", type=float, default=10.0, help="Test timeout in seconds")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--bad-ssl", action="store_true", help="Test relay with bad SSL cert")
    parser.add_argument("--onion", action="store_true", help="Test Tor .onion relay")
    parser.add_argument("--selective", action="store_true", help="Run selective tests")
    parser.add_argument("--errors", action="store_true", help="Test error handling")
    parser.add_argument("--json", action="store_true", help="Print full JSON output")
    parser.add_argument("--summary", action="store_true", help="Print summary info")
    parser.add_argument("--all", action="store_true", help="Run all tests")
    args = parser.parse_args()

    # Setup
    setup_logging(args.debug)
    city_reader, asn_reader = load_geoip_readers()

    print("=" * 60)
    print("  NIP-66 Test Script")
    print("=" * 60)
    print(f"\nGeoIP City DB:  {city_reader is not None}")
    print(f"GeoIP ASN DB:   {asn_reader is not None}")

    # Generate test keys
    keys = Keys.generate()
    print(f"Test pubkey:    {keys.public_key().to_hex()[:16]}...")

    # Create event builder and filter
    event_builder = EventBuilder.text_note("NIP-66 test event")
    read_filter = Filter().kind(Kind(1)).limit(1)
    print("Event builder:  Ready")
    print("Read filter:    Ready")

    relay = Relay(args.relay)

    # Determine if proxy is needed for the relay
    proxy_for_relay = args.proxy if relay.network != "clearnet" else None

    # Run tests based on flags
    if args.all or (not any([args.bad_ssl, args.onion, args.selective, args.errors, args.summary])):
        # Default: run full test on specified relay
        nip66 = await test_full_relay(
            args.relay,
            keys,
            event_builder,
            read_filter,
            city_reader,
            asn_reader,
            proxy_url=proxy_for_relay,
            timeout=args.timeout,
        )

        if nip66:
            print_rtt_results(nip66)
            print_ssl_results(nip66)
            print_geo_results(nip66)
            print_dns_results(nip66)
            print_http_results(nip66)

            # Always print full JSON structure
            print_full_json(nip66)

    if args.bad_ssl or args.all:
        await test_bad_ssl_relay(keys, event_builder, read_filter, city_reader, asn_reader)

    if args.onion or args.all:
        await test_onion_relay(keys, event_builder, read_filter, args.proxy)

    if args.selective or args.all:
        await test_selective(relay)

    if args.errors or args.all:
        await test_error_handling(relay)

    if args.summary or args.all:
        print_summary()

    # Cleanup
    if city_reader:
        city_reader.close()
    if asn_reader:
        asn_reader.close()

    print("\n" + "=" * 60)
    print("  Done")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
