#!/usr/bin/env python3
"""
Test NIP-11 Relay Information Document

Interactive script for testing the `Nip11` model:
- Fetch NIP-11 documents from relays (clearnet and overlay networks)
- Data access via `metadata.data["key"]`
- Proxy support for Tor/I2P/Loki relays
- Parsing and validation
- Error handling

Usage:
    python notebooks/test_nip11.py
    python notebooks/test_nip11.py --relay wss://relay.damus.io
    python notebooks/test_nip11.py --onion --proxy socks5://127.0.0.1:9050
    python notebooks/test_nip11.py --multiple
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

from models.metadata import Metadata
from models.nip11 import Nip11, Nip11FetchError
from models.relay import NetworkType, Relay


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

DEFAULT_RELAY = "wss://relay.damus.io"
ONION_RELAY = "ws://oxtrdevav64z64yb7x6rjg4ntzqjhedm5b5zjqulugknhzr46ny2qbad.onion"
TOR_PROXY = "socks5://127.0.0.1:9050"

MULTIPLE_RELAYS = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.nostr.band",
    "wss://nostr.wine",
    "wss://relay.snort.social",
]


# -----------------------------------------------------------------------------
# Setup
# -----------------------------------------------------------------------------


def setup_logging(debug: bool = False) -> None:
    """Configure logging for nip11 module."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("models.nip11").setLevel(level)


def print_separator(title: str) -> None:
    """Print a section separator."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print("=" * 60)


# -----------------------------------------------------------------------------
# Test Functions
# -----------------------------------------------------------------------------


async def test_basic_fetch(
    relay_url: str,
    proxy_url: str | None = None,
    timeout: float = 10.0,
) -> Nip11 | None:
    """Fetch NIP-11 document from a relay."""
    relay = Relay(relay_url)
    print_separator(f"Fetch: {relay.url}")
    print(f"Network: {relay.network}")
    print(f"Scheme: {relay.scheme}")
    print(f"Host: {relay.host}")
    if proxy_url:
        print(f"Proxy: {proxy_url}")

    try:
        nip11 = await Nip11.fetch(relay, timeout=timeout, proxy_url=proxy_url)
        print(f"\nFetch successful: {nip11 is not None}")
        print(f"Type: {type(nip11).__name__}")
        return nip11

    except Nip11FetchError as e:
        print(f"\nFetch failed: {e}")
        print(f"Cause: {type(e.cause).__name__}: {e.cause}")
        return None


def print_base_fields(nip11: Nip11) -> None:
    """Print base NIP-11 fields."""
    print_separator("Base Fields")
    data = nip11.metadata.data
    print(f"name:             {data.get('name')}")
    print(f"description:      {data.get('description')}")
    print(f"pubkey:           {data.get('pubkey')}")
    print(f"contact:          {data.get('contact')}")
    print(f"software:         {data.get('software')}")
    print(f"version:          {data.get('version')}")
    print(f"banner:           {data.get('banner')}")
    print(f"icon:             {data.get('icon')}")


def print_nips(nip11: Nip11) -> None:
    """Print supported NIPs."""
    print_separator("Supported NIPs")
    nips = nip11.supported_nips
    if nips:
        print(f"Count: {len(nips)}")
        print(f"NIPs:  {nips}")
    else:
        print("No NIPs listed")


def print_limitation(nip11: Nip11) -> None:
    """Print limitation object."""
    print_separator("Limitation")
    limitation = nip11.limitation
    if limitation and any(v is not None for v in limitation.values()):
        print(f"max_message_length:   {limitation.get('max_message_length')}")
        print(f"max_subscriptions:    {limitation.get('max_subscriptions')}")
        print(f"max_limit:            {limitation.get('max_limit')}")
        print(f"max_subid_length:     {limitation.get('max_subid_length')}")
        print(f"max_event_tags:       {limitation.get('max_event_tags')}")
        print(f"max_content_length:   {limitation.get('max_content_length')}")
        print(f"min_pow_difficulty:   {limitation.get('min_pow_difficulty')}")
        print(f"auth_required:        {limitation.get('auth_required')}")
        print(f"payment_required:     {limitation.get('payment_required')}")
        print(f"restricted_writes:    {limitation.get('restricted_writes')}")
        print(f"created_at_lower:     {limitation.get('created_at_lower_limit')}")
        print(f"created_at_upper:     {limitation.get('created_at_upper_limit')}")
        print(f"default_limit:        {limitation.get('default_limit')}")
    else:
        print("No limitations defined")


def print_retention(nip11: Nip11) -> None:
    """Print retention policies."""
    print_separator("Retention Policies")
    retention = nip11.retention
    if retention:
        for i, entry in enumerate(retention):
            print(f"\n  [{i}] kinds: {entry.get('kinds')}")
            print(f"      time:  {entry.get('time')} seconds")
            print(f"      count: {entry.get('count')}")
    else:
        print("No retention policies defined")


def print_fees(nip11: Nip11) -> None:
    """Print fee schedules."""
    print_separator("Fees")
    fees = nip11.metadata.data.get("fees", {})

    if fees and any(v is not None for v in fees.values()):
        for category in ("admission", "subscription", "publication"):
            fee_list = fees.get(category)
            if fee_list:
                print(f"\n  {category.upper()}:")
                for entry in fee_list:
                    amount = entry.get("amount", "?")
                    unit = entry.get("unit", "?")
                    period = entry.get("period")
                    kinds = entry.get("kinds")
                    line = f"    {amount} {unit}"
                    if period:
                        line += f" / {period}s"
                    if kinds:
                        line += f" (kinds: {kinds})"
                    print(line)
    else:
        print("No fees defined")


def print_community(nip11: Nip11) -> None:
    """Print community-related fields."""
    print_separator("Community & Policies")
    data = nip11.metadata.data
    print(f"relay_countries:    {data.get('relay_countries')}")
    print(f"language_tags:      {data.get('language_tags')}")
    print(f"tags:               {data.get('tags')}")
    print(f"posting_policy:     {data.get('posting_policy')}")
    print(f"privacy_policy:     {data.get('privacy_policy')}")
    print(f"terms_of_service:   {data.get('terms_of_service')}")
    print(f"payments_url:       {data.get('payments_url')}")


def print_full_json(nip11: Nip11) -> None:
    """Print full JSON output."""
    print_separator("Full JSON Output")
    print(json.dumps(nip11.metadata.data, indent=2, default=str))


def print_relay_metadata(nip11: Nip11) -> None:
    """Print RelayMetadata conversion."""
    print_separator("RelayMetadata Conversion")
    relay_metadata = nip11.to_relay_metadata()
    print(f"type:          {type(relay_metadata).__name__}")
    print(f"metadata_type: {relay_metadata.metadata_type}")
    print(f"generated_at:  {relay_metadata.generated_at}")
    print(f"relay_url:     {relay_metadata.relay.url}")


async def test_multiple_relays(relay_urls: list[str], timeout: float = 5.0) -> None:
    """Test multiple relays in parallel."""
    print_separator("Multiple Relays Test")

    async def fetch_safe(url: str) -> tuple[str, Nip11 | None, Exception | None]:
        relay = Relay(url)
        try:
            nip11 = await Nip11.fetch(relay, timeout=timeout)
            return url, nip11, None
        except Exception as e:
            return url, None, e

    results = await asyncio.gather(*[fetch_safe(url) for url in relay_urls])

    print("\nResults:")
    for url, nip11, error in results:
        if nip11:
            data = nip11.metadata.data
            nips = data.get("supported_nips") or []
            name = data.get("name") or "No name"
            print(f"  ✓ {url}")
            print(f"      name: {name}")
            print(f"      nips: {len(nips)}")
        else:
            print(f"  ✗ {url}")
            print(f"      error: {type(error).__name__}")


async def test_onion_relay(proxy_url: str, timeout: float = 30.0) -> None:
    """Test Tor relay via SOCKS5 proxy."""
    print_separator(f"Tor Relay Test: {ONION_RELAY}")
    print(f"Proxy: {proxy_url}")
    print("\nNote: .onion relays require a running Tor proxy")

    relay = Relay(ONION_RELAY)
    print(f"Network: {relay.network}")

    try:
        nip11 = await Nip11.fetch(relay, timeout=timeout, proxy_url=proxy_url)
        data = nip11.metadata.data
        print(f"\nFetch successful!")
        print(f"name: {data.get('name')}")
        print(f"software: {data.get('software')}")
        print(f"version: {data.get('version')}")
        nips = data.get("supported_nips") or []
        print(f"nips: {len(nips)}")

    except Nip11FetchError as e:
        print(f"\nFetch failed: {e}")
        print(f"Cause: {type(e.cause).__name__}")
        print("\nMake sure Tor proxy is running:")
        print("  docker run -d -p 9050:9050 dperson/torproxy")


async def test_synthetic_data() -> None:
    """Test Nip11 with synthetic data."""
    print_separator("Synthetic Data Test")

    test_relay = Relay("wss://test.relay.example")

    synthetic_data = {
        "name": "Test Relay",
        "description": "A test relay for parsing",
        "supported_nips": [1, 2, 4, 9, 11, 40],
        "limitation": {
            "max_message_length": 128000,
            "auth_required": True,
        },
        "fees": {
            "admission": [{"amount": 21000, "unit": "sats"}],
        },
    }

    nip11 = Nip11(relay=test_relay, metadata=Metadata(synthetic_data))
    data = nip11.metadata.data

    print(f"name:           {data.get('name')}")
    print(f"supported_nips: {data.get('supported_nips')}")
    print(f"limitation:     {data.get('limitation')}")
    print(f"fees:           {data.get('fees')}")


async def test_parsing_edge_cases() -> None:
    """Test parsing edge cases."""
    print_separator("Parsing Edge Cases")

    test_relay = Relay("wss://test.relay.example")

    # Invalid types are filtered out
    print("\n--- Invalid Types ---")
    invalid_data = {
        "name": 12345,  # Should be string -> None
        "description": "Valid description",
        "supported_nips": [1, 2, "three", 4],  # Non-ints filtered
    }

    nip11_invalid = Nip11(relay=test_relay, metadata=Metadata(invalid_data))
    data = nip11_invalid.metadata.data
    print(f"name: {data.get('name')} (was int -> None)")
    print(f"description: {data.get('description')}")
    print(f"supported_nips: {data.get('supported_nips')} (filtered non-ints)")

    # Empty iterables become None
    print("\n--- Empty Iterables ---")
    empty_data = {
        "name": "Empty Test",
        "supported_nips": [],  # Empty list -> None
        "relay_countries": [],  # Empty list -> None
    }

    nip11_empty = Nip11(relay=test_relay, metadata=Metadata(empty_data))
    data = nip11_empty.metadata.data
    print(f"name: {data.get('name')}")
    print(f"supported_nips: {data.get('supported_nips')} (was [] -> None)")
    print(f"relay_countries: {data.get('relay_countries')} (was [] -> None)")


async def test_error_handling() -> None:
    """Test error handling scenarios."""
    print_separator("Error Handling")

    test_relay = Relay("wss://test.relay.example")

    # Invalid relay URL
    print("\n--- Invalid Relay URL ---")
    invalid_relay = Relay("wss://nonexistent.relay.invalid")
    try:
        await Nip11.fetch(invalid_relay, timeout=3.0)
    except Nip11FetchError as e:
        print(f"Correctly raised: Nip11FetchError")
        print(f"relay: {e.relay.url}")
        print(f"cause: {type(e.cause).__name__}")

    # Empty metadata
    print("\n--- Empty Metadata ---")
    try:
        Nip11(relay=test_relay, metadata=Metadata({}))
    except ValueError as e:
        print(f"Correctly raised: ValueError")
        print(f"message: {e}")


def print_summary() -> None:
    """Print summary information."""
    print_separator("Summary")
    print("""
Key Points:
- Access fields via nip11.metadata.data["key"]
- All schema keys are present (with None for missing)
- Invalid types are silently converted to None
- Empty iterables become None
- Use proxy_url for Tor/I2P/Loki relays

NIP-11 Structure:
┌─────────────────────────────────────────────────────────────┐
│ Base Fields                                                 │
├─────────────────────────────────────────────────────────────┤
│ name, description, banner, icon, pubkey, self, contact      │
│ software, version, supported_nips                           │
│ privacy_policy, terms_of_service, posting_policy            │
│ payments_url                                                │
├─────────────────────────────────────────────────────────────┤
│ Nested Objects                                              │
├─────────────────────────────────────────────────────────────┤
│ limitation  - Server constraints (max_*, auth_required...)  │
│ retention   - Event retention policies (kinds, time, count) │
│ fees        - Fee schedules (admission, subscription, pub)  │
├─────────────────────────────────────────────────────────────┤
│ Lists                                                       │
├─────────────────────────────────────────────────────────────┤
│ relay_countries - ISO country codes                         │
│ language_tags   - BCP 47 language tags                      │
│ tags            - Community tags (e.g., "sfw-only")         │
└─────────────────────────────────────────────────────────────┘

Class Defaults:
  _FETCH_TIMEOUT:  10.0 seconds
  _FETCH_MAX_SIZE: 65536 bytes (64 KB)
""")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------


async def main() -> None:
    """Run NIP-11 tests."""
    parser = argparse.ArgumentParser(description="Test NIP-11 relay information documents")
    parser.add_argument("--relay", default=DEFAULT_RELAY, help="Relay URL to test")
    parser.add_argument("--proxy", default=TOR_PROXY, help="SOCKS5 proxy URL")
    parser.add_argument("--timeout", type=float, default=10.0, help="Fetch timeout in seconds")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--multiple", action="store_true", help="Test multiple relays")
    parser.add_argument("--onion", action="store_true", help="Test Tor .onion relay")
    parser.add_argument("--synthetic", action="store_true", help="Test synthetic data")
    parser.add_argument("--edge-cases", action="store_true", help="Test parsing edge cases")
    parser.add_argument("--errors", action="store_true", help="Test error handling")
    parser.add_argument("--json", action="store_true", help="Print full JSON output")
    parser.add_argument("--summary", action="store_true", help="Print summary info")
    parser.add_argument("--all", action="store_true", help="Run all tests")
    args = parser.parse_args()

    # Setup
    setup_logging(args.debug)

    print("=" * 60)
    print("  NIP-11 Test Script")
    print("=" * 60)

    relay = Relay(args.relay)

    # Determine if proxy is needed for the relay
    proxy_for_relay = args.proxy if relay.network != NetworkType.CLEARNET else None

    # Run tests based on flags
    run_default = not any([
        args.multiple,
        args.onion,
        args.synthetic,
        args.edge_cases,
        args.errors,
        args.summary,
    ])

    if args.all or run_default:
        # Default: fetch from specified relay
        nip11 = await test_basic_fetch(
            args.relay,
            proxy_url=proxy_for_relay,
            timeout=args.timeout,
        )

        if nip11:
            print_base_fields(nip11)
            print_nips(nip11)
            print_limitation(nip11)
            print_retention(nip11)
            print_fees(nip11)
            print_community(nip11)
            print_relay_metadata(nip11)

            # Always print full JSON
            print_full_json(nip11)

    if args.multiple or args.all:
        await test_multiple_relays(MULTIPLE_RELAYS)

    if args.onion or args.all:
        await test_onion_relay(args.proxy)

    if args.synthetic or args.all:
        await test_synthetic_data()

    if args.edge_cases or args.all:
        await test_parsing_edge_cases()

    if args.errors or args.all:
        await test_error_handling()

    if args.summary or args.all:
        print_summary()

    print("\n" + "=" * 60)
    print("  Done")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
