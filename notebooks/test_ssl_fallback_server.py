#!/usr/bin/env python3
"""
Local WebSocket Server with Self-Signed Certificate for SSL Fallback Testing

This script:
1. Generates a self-signed SSL certificate (in memory)
2. Starts a minimal Nostr-like WebSocket server on localhost
3. Tests connect_relay() to verify SSL fallback works

Usage:
    python notebooks/test_ssl_fallback_server.py

The server responds to basic Nostr messages:
- REQ: Returns EOSE immediately (no events)
- EVENT: Returns OK with success
- CLOSE: Acknowledges subscription close
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import ssl
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import aiohttp
from aiohttp import web


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Server config
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 9999
SERVER_URL = f"wss://{SERVER_HOST}:{SERVER_PORT}"


def generate_self_signed_cert() -> tuple[str, str]:
    """Generate a self-signed certificate and key.

    Returns:
        Tuple of (cert_path, key_path) as temporary files
    """
    from cryptography import x509
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    # Generate private key
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )

    # Generate certificate
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Test"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "Test"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Test Relay"),
            x509.NameAttribute(NameOID.COMMON_NAME, SERVER_HOST),
        ]
    )

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.utcnow())
        .not_valid_after(datetime(2099, 12, 31))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName(SERVER_HOST),
                    x509.IPAddress(ipaddress.ip_address(SERVER_HOST)),
                ]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256(), default_backend())
    )

    # Write to temp files
    cert_file = tempfile.NamedTemporaryFile(mode="wb", suffix=".pem", delete=False)
    cert_file.write(cert.public_bytes(serialization.Encoding.PEM))
    cert_file.close()

    key_file = tempfile.NamedTemporaryFile(mode="wb", suffix=".pem", delete=False)
    key_file.write(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    key_file.close()

    return cert_file.name, key_file.name


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    """Handle WebSocket connections with basic Nostr protocol support."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    logger.info("Client connected from %s", request.remote)

    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            try:
                data = json.loads(msg.data)
                msg_type = data[0] if data else None

                if msg_type == "REQ":
                    # REQ: ["REQ", sub_id, filter...]
                    sub_id = data[1] if len(data) > 1 else "sub"
                    # Send EOSE immediately (no events)
                    await ws.send_str(json.dumps(["EOSE", sub_id]))
                    logger.debug("REQ %s -> EOSE", sub_id)

                elif msg_type == "EVENT":
                    # EVENT: ["EVENT", event]
                    event = data[1] if len(data) > 1 else {}
                    event_id = event.get("id", "unknown")
                    # Send OK
                    await ws.send_str(json.dumps(["OK", event_id, True, ""]))
                    logger.debug("EVENT %s -> OK", event_id[:8])

                elif msg_type == "CLOSE":
                    # CLOSE: ["CLOSE", sub_id]
                    sub_id = data[1] if len(data) > 1 else "sub"
                    await ws.send_str(json.dumps(["CLOSED", sub_id, ""]))
                    logger.debug("CLOSE %s -> CLOSED", sub_id)

                else:
                    logger.warning("Unknown message type: %s", msg_type)

            except json.JSONDecodeError:
                logger.warning("Invalid JSON: %s", msg.data[:100])
            except Exception as e:
                logger.error("Error handling message: %s", e)

        elif msg.type == aiohttp.WSMsgType.ERROR:
            logger.error("WebSocket error: %s", ws.exception())

    logger.info("Client disconnected")
    return ws


async def run_server(cert_path: str, key_path: str) -> web.AppRunner:
    """Start the WebSocket server with SSL."""
    app = web.Application()
    app.router.add_get("/", websocket_handler)

    # Create SSL context
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(cert_path, key_path)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, SERVER_HOST, SERVER_PORT, ssl_context=ssl_context)
    await site.start()

    return runner


async def test_ssl_fallback() -> bool:
    """Test connect_relay() with the self-signed cert server."""
    from utils.transport import connect_relay

    print(f"\nTesting connect_relay() to {SERVER_URL}")
    print("This should trigger SSL fallback due to self-signed certificate...\n")

    try:
        # Create relay - need to bypass the local address check
        # We'll create a custom Relay-like object with all required attributes
        class TestRelay:
            def __init__(self, url: str):
                self.url = url
                self.network = "clearnet"
                self.host = SERVER_HOST
                self.port = SERVER_PORT

        relay = TestRelay(SERVER_URL)

        client = await connect_relay(relay, timeout=10.0)  # type: ignore

        # If we get here, SSL fallback worked (otherwise would have raised)
        print("✓ PASS: SSL fallback triggered correctly")
        print("  Connected to self-signed cert server via insecure transport")
        await client.disconnect()
        return True

    except Exception as e:
        error_str = str(e).lower()
        if "ssl" in error_str or "certificate" in error_str:
            print(f"✗ FAIL: SSL error not handled: {e}")
        else:
            print(f"✗ FAIL: Unexpected error: {type(e).__name__}: {e}")
        return False


async def test_direct_insecure_connection() -> bool:
    """Test direct connection with insecure client."""
    from datetime import timedelta
    from nostr_sdk import RelayUrl, uniffi_set_event_loop
    from utils.transport import create_insecure_client

    print(f"\nTesting create_insecure_client() to {SERVER_URL}")
    print("This should connect directly without SSL verification...\n")

    try:
        uniffi_set_event_loop(asyncio.get_running_loop())

        client = create_insecure_client()
        relay_url = RelayUrl.parse(SERVER_URL)
        await client.add_relay(relay_url)
        await client.connect()
        await client.wait_for_connection(timedelta(seconds=10))

        relay_obj = await client.relay(relay_url)
        connected = relay_obj.is_connected()
        await client.disconnect()

        if connected:
            print("✓ PASS: Direct insecure connection succeeded")
            return True
        else:
            print("✗ FAIL: Failed to connect with insecure client")
            return False

    except Exception as e:
        print(f"✗ FAIL: Error: {type(e).__name__}: {e}")
        return False


async def test_normal_ssl_fails() -> bool:
    """Test that normal SSL connection fails (as expected)."""
    from datetime import timedelta
    from nostr_sdk import RelayUrl
    from utils.transport import create_client

    print(f"\nTesting create_client() (normal SSL) to {SERVER_URL}")
    print("This should FAIL due to self-signed certificate...\n")

    try:
        client = create_client()
        relay_url = RelayUrl.parse(SERVER_URL)
        await client.add_relay(relay_url)
        await client.connect()
        await client.wait_for_connection(timedelta(seconds=5))

        relay_obj = await client.relay(relay_url)
        connected = relay_obj.is_connected()
        await client.disconnect()

        if connected:
            print("✗ UNEXPECTED: Normal SSL connection succeeded (should have failed)")
            return False
        else:
            print("✓ PASS: Normal SSL connection failed as expected")
            return True

    except Exception as e:
        error_str = str(e).lower()
        if "ssl" in error_str or "certificate" in error_str or "cert" in error_str:
            print(f"✓ PASS: Normal SSL connection failed with SSL error: {e}")
            return True
        else:
            print(f"✓ PASS: Normal SSL connection failed: {type(e).__name__}")
            return True


async def main() -> None:
    """Main entry point."""
    print("=" * 60)
    print("  SSL Fallback Test with Self-Signed Certificate Server")
    print("=" * 60)

    # Check for cryptography library
    try:
        from cryptography import x509  # noqa: F401
    except ImportError:
        print("\nError: 'cryptography' package required")
        print("Install with: pip install cryptography")
        sys.exit(1)

    # Generate self-signed certificate
    print("\n1. Generating self-signed certificate...")
    cert_path, key_path = generate_self_signed_cert()
    print(f"   Cert: {cert_path}")
    print(f"   Key:  {key_path}")

    # Start server
    print(f"\n2. Starting WebSocket server on {SERVER_URL}...")
    runner = await run_server(cert_path, key_path)
    print("   Server running!")

    # Give server time to start
    await asyncio.sleep(0.5)

    results = []

    try:
        # Test 1: Normal SSL should fail
        print("\n" + "=" * 60)
        print("  Test 1: Normal SSL Connection (should fail)")
        print("=" * 60)
        results.append(("Normal SSL fails", await test_normal_ssl_fails()))

        # Test 2: Direct insecure connection should work
        print("\n" + "=" * 60)
        print("  Test 2: Direct Insecure Connection (should work)")
        print("=" * 60)
        results.append(("Insecure direct", await test_direct_insecure_connection()))

        # Test 3: SSL fallback should work
        print("\n" + "=" * 60)
        print("  Test 3: SSL Fallback via connect_relay() (should work)")
        print("=" * 60)
        results.append(("SSL fallback", await test_ssl_fallback()))

    finally:
        # Cleanup
        print("\n4. Shutting down server...")
        await runner.cleanup()

        # Remove temp files
        import os

        os.unlink(cert_path)
        os.unlink(key_path)
        print("   Cleanup complete!")

    # Summary
    print("\n" + "=" * 60)
    print("  Test Summary")
    print("=" * 60)

    passed = sum(1 for _, p in results if p)
    total = len(results)

    for name, result in results:
        status = "✓" if result else "✗"
        print(f"  {status} {name}")

    print(f"\nPassed: {passed}/{total}")

    if passed == total:
        print("\n✓ All tests passed! SSL fallback is working correctly.")
    else:
        print("\n✗ Some tests failed.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
