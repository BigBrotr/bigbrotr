"""Shared fixtures for NIP-11 tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from bigbrotr.models.relay import Relay
from bigbrotr.nips.nip11 import (
    Nip11,
    Nip11InfoData,
    Nip11InfoDataFeeEntry,
    Nip11InfoDataFees,
    Nip11InfoDataLimitation,
    Nip11InfoDataRetentionEntry,
    Nip11InfoLogs,
    Nip11InfoMetadata,
)


# =============================================================================
# Relay Fixtures
# =============================================================================


@pytest.fixture
def relay() -> Relay:
    """Standard clearnet relay fixture."""
    return Relay("wss://relay.example.com")


@pytest.fixture
def relay_with_port() -> Relay:
    """Clearnet relay with non-default port."""
    return Relay("wss://relay.example.com:8080")


@pytest.fixture
def relay_with_path() -> Relay:
    """Clearnet relay with path."""
    return Relay("wss://relay.example.com/nostr")


@pytest.fixture
def relay_with_port_and_path() -> Relay:
    """Clearnet relay with port and path."""
    return Relay("wss://relay.example.com:8080/nostr/v1")


@pytest.fixture
def tor_relay() -> Relay:
    """Tor (.onion) relay fixture."""
    return Relay("ws://abc123xyz789abc123xyz789abc123xyz789abc123xyz789abcdefgh.onion")


@pytest.fixture
def i2p_relay() -> Relay:
    """I2P (.i2p) relay fixture."""
    return Relay("ws://example.i2p")


@pytest.fixture
def loki_relay() -> Relay:
    """Lokinet (.loki) relay fixture."""
    return Relay("ws://example.loki")


@pytest.fixture
def ipv6_relay() -> Relay:
    """IPv6 relay fixture using a public address."""
    return Relay("wss://[2607:f8b0:4000::1]:8080")


# =============================================================================
# NIP-11 Data Fixtures
# =============================================================================


@pytest.fixture
def complete_nip11_data() -> dict[str, Any]:
    """Complete NIP-11 data dict matching spec with all fields populated."""
    return {
        "name": "Test Relay",
        "description": "A test relay for unit tests",
        "banner": "https://example.com/banner.jpg",
        "icon": "https://example.com/icon.jpg",
        "pubkey": "a" * 64,
        "self": "b" * 64,
        "contact": "admin@example.com",
        "software": "nostr-rs-relay",
        "version": "1.0.0",
        "privacy_policy": "https://example.com/privacy",
        "terms_of_service": "https://example.com/tos",
        "posting_policy": "https://example.com/posting",
        "payments_url": "https://example.com/pay",
        "supported_nips": [1, 11, 42, 65],
        "limitation": {
            "max_message_length": 65535,
            "max_subscriptions": 20,
            "max_limit": 5000,
            "max_subid_length": 256,
            "max_event_tags": 2000,
            "max_content_length": 65535,
            "min_pow_difficulty": 0,
            "auth_required": False,
            "payment_required": True,
            "restricted_writes": True,
            "created_at_lower_limit": 0,
            "created_at_upper_limit": 2147483647,
            "default_limit": 100,
        },
        "retention": [
            {"kinds": [0, 3]},
            {"kinds": [[10000, 19999]], "time": 86400},
            {"kinds": [[30000, 39999]], "count": 100},
        ],
        "relay_countries": ["US", "CA"],
        "language_tags": ["en", "en-US"],
        "tags": ["sfw-only", "bitcoin-only"],
        "fees": {
            "admission": [{"amount": 1000, "unit": "sats"}],
            "subscription": [{"amount": 5000, "unit": "sats", "period": 2628003}],
            "publication": [{"kinds": [4], "amount": 100, "unit": "msats"}],
        },
    }


@pytest.fixture
def minimal_nip11_data() -> dict[str, Any]:
    """Minimal NIP-11 data dict with only name."""
    return {"name": "Minimal Relay"}


@pytest.fixture
def unicode_nip11_data() -> dict[str, Any]:
    """NIP-11 data with unicode characters."""
    return {
        "name": "Relay del Sol",
        "description": "Un relay para todos los nostrichos",
        "tags": ["espanol", "latinoamerica"],
        "language_tags": ["es", "es-MX", "pt-BR"],
    }


# =============================================================================
# Model Instance Fixtures
# =============================================================================


@pytest.fixture
def limitation() -> Nip11InfoDataLimitation:
    """Nip11InfoDataLimitation instance with common values."""
    return Nip11InfoDataLimitation(
        max_message_length=65535,
        max_subscriptions=20,
        auth_required=False,
        payment_required=True,
    )


@pytest.fixture
def retention_entry() -> Nip11InfoDataRetentionEntry:
    """Nip11InfoDataRetentionEntry instance."""
    return Nip11InfoDataRetentionEntry(
        kinds=[1, 2, (10000, 19999)],
        time=86400,
    )


@pytest.fixture
def fee_entry() -> Nip11InfoDataFeeEntry:
    """Nip11InfoDataFeeEntry instance."""
    return Nip11InfoDataFeeEntry(
        amount=1000,
        unit="sats",
        period=2628003,
    )


@pytest.fixture
def fees() -> Nip11InfoDataFees:
    """Nip11InfoDataFees instance with admission fee."""
    return Nip11InfoDataFees(
        admission=[Nip11InfoDataFeeEntry(amount=1000, unit="sats")],
    )


@pytest.fixture
def info_data(complete_nip11_data: dict[str, Any]) -> Nip11InfoData:
    """Nip11InfoData instance from complete data."""
    return Nip11InfoData.from_dict(complete_nip11_data)


@pytest.fixture
def info_data_empty() -> Nip11InfoData:
    """Empty Nip11InfoData instance with defaults."""
    return Nip11InfoData()


@pytest.fixture
def info_logs_success() -> Nip11InfoLogs:
    """Successful Nip11InfoLogs instance."""
    return Nip11InfoLogs(success=True)


@pytest.fixture
def info_logs_failure() -> Nip11InfoLogs:
    """Failed Nip11InfoLogs instance with reason."""
    return Nip11InfoLogs(success=False, reason="Connection timeout")


@pytest.fixture
def info_metadata(
    info_data: Nip11InfoData,
    info_logs_success: Nip11InfoLogs,
) -> Nip11InfoMetadata:
    """Nip11InfoMetadata instance with successful fetch."""
    return Nip11InfoMetadata(data=info_data, logs=info_logs_success)


@pytest.fixture
def info_metadata_failed(
    info_data_empty: Nip11InfoData,
    info_logs_failure: Nip11InfoLogs,
) -> Nip11InfoMetadata:
    """Nip11InfoMetadata instance with failed fetch."""
    return Nip11InfoMetadata(data=info_data_empty, logs=info_logs_failure)


@pytest.fixture
def nip11(
    relay: Relay,
    info_metadata: Nip11InfoMetadata,
) -> Nip11:
    """Nip11 instance with complete data and successful info retrieval."""
    return Nip11(
        relay=relay,
        info=info_metadata,
        generated_at=1234567890,
    )


@pytest.fixture
def nip11_failed(
    relay: Relay,
    info_metadata_failed: Nip11InfoMetadata,
) -> Nip11:
    """Nip11 instance with failed info retrieval."""
    return Nip11(
        relay=relay,
        info=info_metadata_failed,
        generated_at=1234567890,
    )


@pytest.fixture
def nip11_no_info(relay: Relay) -> Nip11:
    """Nip11 instance with info=None."""
    return Nip11(
        relay=relay,
        info=None,
        generated_at=1234567890,
    )


# =============================================================================
# Mock HTTP Response Fixtures
# =============================================================================


@pytest.fixture
def mock_http_response_success() -> MagicMock:
    """Mock successful HTTP response with valid NIP-11 JSON."""
    response = AsyncMock()
    response.status = 200
    response.headers = {"Content-Type": "application/nostr+json"}
    response.content.read = AsyncMock(return_value=b'{"name": "Test Relay"}')
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=None)
    return response


@pytest.fixture
def mock_http_response_404() -> MagicMock:
    """Mock 404 HTTP response."""
    response = AsyncMock()
    response.status = 404
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=None)
    return response


@pytest.fixture
def mock_http_response_invalid_content_type() -> MagicMock:
    """Mock HTTP response with invalid Content-Type."""
    response = AsyncMock()
    response.status = 200
    response.headers = {"Content-Type": "text/html"}
    response.content.read = AsyncMock(return_value=b"<html></html>")
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=None)
    return response


@pytest.fixture
def mock_http_response_invalid_json() -> MagicMock:
    """Mock HTTP response with invalid JSON."""
    response = AsyncMock()
    response.status = 200
    response.headers = {"Content-Type": "application/json"}
    response.content.read = AsyncMock(return_value=b"not valid json")
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=None)
    return response


@pytest.fixture
def mock_session_factory():
    """Factory for creating mock aiohttp sessions."""

    def _create_session(response: MagicMock) -> MagicMock:
        session = MagicMock()
        session.get = MagicMock(return_value=response)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        return session

    return _create_session
