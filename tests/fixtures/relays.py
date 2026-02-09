"""Canonical relay fixtures shared across all test packages.

Usage: Registered via ``pytest_plugins`` in the root ``conftest.py``.
"""

from __future__ import annotations

import pytest

from bigbrotr.models import Relay


# =============================================================================
# Individual relay fixtures
# =============================================================================


@pytest.fixture
def relay_clearnet() -> Relay:
    """Standard clearnet wss:// relay."""
    return Relay("wss://relay.example.com", discovered_at=1700000000)


@pytest.fixture
def relay_clearnet_with_port() -> Relay:
    """Clearnet relay with explicit port."""
    return Relay("wss://relay.example.com:8443", discovered_at=1700000000)


@pytest.fixture
def relay_clearnet_ws() -> Relay:
    """Clearnet ws:// (non-TLS) relay."""
    return Relay("ws://relay.example.com", discovered_at=1700000000)


@pytest.fixture
def relay_tor() -> Relay:
    """Tor (.onion) relay with valid 56-char v3 address."""
    onion = "a" * 56
    return Relay(f"wss://{onion}.onion", discovered_at=1700000000)


@pytest.fixture
def relay_i2p() -> Relay:
    """I2P (.i2p) relay."""
    return Relay("wss://example.i2p", discovered_at=1700000000)


@pytest.fixture
def relay_loki() -> Relay:
    """Lokinet (.loki) relay."""
    return Relay("wss://example.loki", discovered_at=1700000000)


@pytest.fixture
def relay_ipv6() -> Relay:
    """IPv6 relay with explicit port."""
    return Relay("wss://[2607:f8b0:4000::1]:8080", discovered_at=1700000000)


# =============================================================================
# Parametrized overlay fixture
# =============================================================================


@pytest.fixture(
    params=["tor", "i2p", "loki"],
    ids=["tor", "i2p", "loki"],
)
def relay_overlay(request: pytest.FixtureRequest) -> Relay:
    """Parametrized overlay relay (tor, i2p, loki)."""
    urls = {
        "tor": f"wss://{'a' * 56}.onion",
        "i2p": "wss://example.i2p",
        "loki": "wss://example.loki",
    }
    return Relay(urls[request.param], discovered_at=1700000000)


# =============================================================================
# Batch fixture
# =============================================================================


@pytest.fixture
def relay_batch() -> list[Relay]:
    """Batch of 10 clearnet relays for bulk operation tests."""
    return [Relay(f"wss://relay{i}.example.com", discovered_at=1700000000) for i in range(10)]
