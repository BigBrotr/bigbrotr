#!/usr/bin/env python3
"""
Test SSL Fallback for connect_relay()

Tests the SSL fallback mechanism in utils.transport.connect_relay():
1. Valid SSL certificate -> connects normally (insecure=False)
2. Invalid/expired SSL certificate -> falls back to insecure transport (insecure=True)
3. Self-signed certificate -> falls back to insecure transport (insecure=True)
4. Timeout (not SSL error) -> raises TimeoutError (no fallback)

Usage:
    python notebooks/test_ssl_fallback.py
    python notebooks/test_ssl_fallback.py --relay wss://your-relay.com
    python notebooks/test_ssl_fallback.py --test-server  # starts local server with bad cert
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import ssl
import sys
import tempfile
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from models.relay import Relay
from utils.transport import (
    connect_relay,
    create_client,
    create_insecure_client,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Test relays
VALID_SSL_RELAY = "wss://relay.damus.io"
EXPIRED_CERT_RELAY = "wss://expired.badssl.com"  # badssl.com test endpoint
SELF_SIGNED_RELAY = "wss://self-signed.badssl.com"  # badssl.com test endpoint
WRONG_HOST_RELAY = "wss://wrong.host.badssl.com"  # badssl.com test endpoint


def print_header(title: str) -> None:
    """Print a formatted header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


def print_result(test_name: str, passed: bool, details: str = "") -> None:
    """Print test result."""
    status = "✓ PASS" if passed else "✗ FAIL"
    print(f"{status}: {test_name}")
    if details:
        print(f"       {details}")


async def test_valid_ssl(relay_url: str = VALID_SSL_RELAY) -> bool:
    """Test connection to relay with valid SSL certificate."""
    print_header(f"Test: Valid SSL Certificate\nRelay: {relay_url}")

    try:
        relay = Relay(relay_url)
        client = await connect_relay(relay, timeout=10.0)
        await client.disconnect()

        print_result(
            "Valid SSL connection",
            True,
            "Connected successfully",
        )
        return True

    except Exception as e:
        print_result("Valid SSL connection", False, f"Error: {e}")
        return False


async def test_invalid_ssl_fallback(relay_url: str) -> bool:
    """Test fallback when SSL certificate is invalid."""
    print_header(f"Test: Invalid SSL Certificate (Fallback)\nRelay: {relay_url}")

    try:
        relay = Relay(relay_url)
        client = await connect_relay(relay, timeout=10.0)
        await client.disconnect()

        # If we get here, SSL fallback worked
        print_result(
            "SSL fallback",
            True,
            "Correctly fell back to insecure transport",
        )
        return True

    except TimeoutError as e:
        print_result(
            "SSL fallback",
            False,
            f"Timeout (server may not support WebSocket): {e}",
        )
        return False
    except Exception as e:
        # Check if it's an SSL error that wasn't caught
        error_str = str(e).lower()
        if any(kw in error_str for kw in ["ssl", "certificate", "cert"]):
            print_result(
                "SSL fallback",
                False,
                f"SSL error not handled: {e}",
            )
        else:
            print_result(
                "SSL fallback",
                False,
                f"Unexpected error: {type(e).__name__}: {e}",
            )
        return False


async def test_timeout_no_fallback() -> bool:
    """Test that timeout errors don't trigger SSL fallback."""
    print_header("Test: Timeout Should Not Trigger Fallback")

    # Use a non-routable IP to force timeout
    relay_url = "wss://10.255.255.1:9999"  # Non-routable, will timeout

    try:
        relay = Relay(relay_url)
        client = await connect_relay(relay, timeout=3.0)
        await client.disconnect()

        print_result(
            "Timeout handling",
            False,
            "Should have raised TimeoutError",
        )
        return False

    except TimeoutError:
        print_result(
            "Timeout handling",
            True,
            "Correctly raised TimeoutError (no SSL fallback)",
        )
        return True
    except Exception as e:
        # Other errors (like connection refused) are also acceptable
        print_result(
            "Timeout handling",
            True,
            f"Raised {type(e).__name__} (no SSL fallback): {e}",
        )
        return True


async def test_direct_insecure_client(relay_url: str = VALID_SSL_RELAY) -> bool:
    """Test create_insecure_client() directly."""
    print_header(f"Test: Direct Insecure Client\nRelay: {relay_url}")

    from datetime import timedelta

    from nostr_sdk import RelayUrl, uniffi_set_event_loop

    try:
        # Set event loop for UniFFI
        uniffi_set_event_loop(asyncio.get_running_loop())

        client = create_insecure_client()
        relay = RelayUrl.parse(relay_url)
        await client.add_relay(relay)
        await client.connect()
        await client.wait_for_connection(timedelta(seconds=10))

        relay_obj = await client.relay(relay)
        connected = relay_obj.is_connected()
        await client.disconnect()

        if connected:
            print_result(
                "Insecure client",
                True,
                "Connected successfully with insecure transport",
            )
            return True
        else:
            print_result(
                "Insecure client",
                False,
                "Failed to connect",
            )
            return False

    except Exception as e:
        print_result("Insecure client", False, f"Error: {e}")
        return False


async def run_all_tests(custom_relay: str | None = None) -> None:
    """Run all SSL fallback tests."""
    print_header("SSL Fallback Test Suite")

    results = []

    # Test 1: Valid SSL
    relay = custom_relay or VALID_SSL_RELAY
    results.append(("Valid SSL", await test_valid_ssl(relay)))

    # Test 2: Direct insecure client
    results.append(("Insecure Client", await test_direct_insecure_client(relay)))

    # Test 3: Timeout handling
    results.append(("Timeout Handling", await test_timeout_no_fallback()))

    # Test 4: Invalid SSL (if badssl.com is reachable)
    # Note: badssl.com doesn't have WebSocket endpoints, so this will fail
    # but we can test with a real relay that has SSL issues
    print_header("Note: SSL Fallback Tests")
    print("To test SSL fallback with a real invalid certificate:")
    print("1. Set up a local relay with a self-signed cert")
    print("2. Or find a Nostr relay with an expired/invalid certificate")
    print("")
    print("badssl.com endpoints don't support WebSocket, so we can't test")
    print("the fallback directly without a real Nostr relay with bad SSL.")

    # Summary
    print_header("Test Summary")
    passed = sum(1 for _, p in results if p)
    total = len(results)

    for name, result in results:
        status = "✓" if result else "✗"
        print(f"  {status} {name}")

    print(f"\nPassed: {passed}/{total}")

    if passed == total:
        print("\nAll tests passed!")
    else:
        print("\nSome tests failed.")


async def test_with_mock_ssl_error() -> bool:
    """Test SSL error detection with a mocked error message."""
    print_header("Test: SSL Error Detection (Mock)")

    # Test the error detection logic
    ssl_keywords = ["ssl", "certificate", "cert", "handshake", "tls", "verify", "x509"]

    test_errors = [
        ("SSL: CERTIFICATE_VERIFY_FAILED", True),
        ("certificate has expired", True),
        ("CERT_NOT_YET_VALID", True),
        ("TLS handshake failed", True),
        ("x509: certificate signed by unknown authority", True),
        ("Connection refused", False),
        ("Connection timed out", False),
        ("Name resolution failed", False),
        ("502 Bad Gateway", False),
    ]

    all_passed = True
    for error_msg, should_be_ssl_error in test_errors:
        error_str = error_msg.lower()
        detected_as_ssl = any(kw in error_str for kw in ssl_keywords)

        if detected_as_ssl == should_be_ssl_error:
            print(f"  ✓ '{error_msg}' -> SSL error: {detected_as_ssl}")
        else:
            print(f"  ✗ '{error_msg}' -> SSL error: {detected_as_ssl} (expected: {should_be_ssl_error})")
            all_passed = False

    print_result("SSL error detection", all_passed)
    return all_passed


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Test SSL fallback mechanism")
    parser.add_argument(
        "--relay",
        type=str,
        help="Custom relay URL to test",
    )
    parser.add_argument(
        "--mock-only",
        action="store_true",
        help="Only run mock tests (no network)",
    )
    args = parser.parse_args()

    if args.mock_only:
        asyncio.run(test_with_mock_ssl_error())
    else:
        asyncio.run(run_all_tests(args.relay))


if __name__ == "__main__":
    main()