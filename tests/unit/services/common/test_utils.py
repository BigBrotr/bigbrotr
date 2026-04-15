"""Unit tests for services.common.utils module.

Tests:
- try_parse_relay: valid URLs, whitespace handling, invalid inputs, edge cases
- parse_relay_row: DB row construction, network cross-check, invalid rows
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from bigbrotr.models import Relay
from bigbrotr.services.common.utils import (
    batch_size_for,
    batched_insert,
    parse_relay_row,
    try_parse_relay,
)


@pytest.fixture
def query_brotr() -> MagicMock:
    """Create a mock Brotr with a configurable batch size."""
    brotr = MagicMock()
    brotr.config.batch.max_size = 1000
    return brotr


# ============================================================================
# try_parse_relay Tests
# ============================================================================


class TestParseRelayUrl:
    """Tests for try_parse_relay function."""

    def test_valid_wss(self) -> None:
        """Test parsing a valid wss:// URL."""
        result = try_parse_relay("wss://relay.example.com")

        assert isinstance(result, Relay)
        assert result.url == "wss://relay.example.com"

    def test_valid_ws_clearnet_sanitized(self) -> None:
        """Test that ws:// clearnet URL is sanitized to wss://."""
        result = try_parse_relay("ws://relay.example.com")

        assert result is not None
        assert result.url == "wss://relay.example.com"
        assert result.scheme == "wss"

    def test_strips_whitespace(self) -> None:
        """Test that leading/trailing whitespace is stripped."""
        result = try_parse_relay("  wss://relay.example.com  ")

        assert isinstance(result, Relay)
        assert result.url == "wss://relay.example.com"

    def test_empty_returns_none(self) -> None:
        """Test that empty string returns None."""
        assert try_parse_relay("") is None

    def test_whitespace_only_returns_none(self) -> None:
        """Test that whitespace-only string returns None."""
        assert try_parse_relay("   ") is None

    def test_none_input_returns_none(self) -> None:
        """Test that None input returns None."""
        assert try_parse_relay(None) is None  # type: ignore[arg-type]

    def test_non_string_returns_none(self) -> None:
        """Test that non-string input returns None."""
        assert try_parse_relay(12345) is None  # type: ignore[arg-type]

    def test_invalid_url_returns_none(self) -> None:
        """Test that invalid URL returns None."""
        assert try_parse_relay("not-a-valid-url") is None

    def test_local_url_returns_none_by_default(self) -> None:
        """Local relays are still rejected by the default application policy."""
        assert try_parse_relay("wss://127.0.0.1") is None

    def test_local_url_allowed_when_requested(self) -> None:
        """Local relays can be enabled explicitly for library/dev use."""
        result = try_parse_relay("wss://127.0.0.1", allow_local=True)

        assert isinstance(result, Relay)
        assert result.url == "wss://127.0.0.1"
        assert result.network.value == "local"

    def test_discovered_at(self) -> None:
        """Test parsing with an explicit discovered_at timestamp."""
        result = try_parse_relay("wss://relay.example.com", discovered_at=1700000000)

        assert isinstance(result, Relay)
        assert result.discovered_at == 1700000000

    def test_discovered_at_none_uses_default(self) -> None:
        """Test that discovered_at=None lets Relay use current time."""
        result = try_parse_relay("wss://relay.example.com")

        assert isinstance(result, Relay)
        assert result.discovered_at > 0

    def test_tor_url(self) -> None:
        """Test parsing a valid .onion relay URL."""
        url = "ws://juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion"
        result = try_parse_relay(url)

        assert isinstance(result, Relay)
        assert result.url == url

    def test_invalid_discovered_at_type_returns_none(self) -> None:
        """Test that TypeError from Relay constructor returns None."""
        result = try_parse_relay("wss://relay.example.com", discovered_at="not_an_int")  # type: ignore[arg-type]

        assert result is None


class TestBatchedInsert:
    """Tests for the shared batching helper."""

    async def test_empty_returns_zero(self, query_brotr: MagicMock) -> None:
        method = AsyncMock(return_value=5)

        result = await batched_insert(query_brotr, [], method)

        assert result == 0
        method.assert_not_called()

    async def test_under_limit_single_call(self, query_brotr: MagicMock) -> None:
        query_brotr.config.batch.max_size = 100
        method = AsyncMock(return_value=3)

        result = await batched_insert(query_brotr, [1, 2, 3], method)

        assert result == 3
        method.assert_awaited_once_with([1, 2, 3])

    async def test_over_limit_splits(self, query_brotr: MagicMock) -> None:
        query_brotr.config.batch.max_size = 2
        method = AsyncMock(return_value=2)

        result = await batched_insert(query_brotr, [1, 2, 3, 4, 5], method)

        assert result == 6
        assert method.await_count == 3
        method.assert_any_await([1, 2])
        method.assert_any_await([3, 4])
        method.assert_any_await([5])

    async def test_exact_multiple(self, query_brotr: MagicMock) -> None:
        query_brotr.config.batch.max_size = 2
        method = AsyncMock(return_value=2)

        result = await batched_insert(query_brotr, [1, 2, 3, 4], method)

        assert result == 4
        assert method.await_count == 2


class TestBatchSizeFor:
    def test_reads_configured_batch_size(self, query_brotr: MagicMock) -> None:
        query_brotr.config.batch.max_size = 7

        assert batch_size_for(query_brotr, 3) == 7

    def test_falls_back_to_record_count_for_lightweight_mocks(self) -> None:
        brotr = MagicMock()
        del brotr.config

        assert batch_size_for(brotr, 3) == 3
        assert batch_size_for(brotr, 0) == 1


# ============================================================================
# parse_relay_row Tests
# ============================================================================


class TestParseRelayRow:
    """Tests for parse_relay_row function."""

    def test_valid_row(self) -> None:
        """Test constructing a Relay from a valid DB row."""
        row = {"url": "wss://relay.example.com", "network": "clearnet", "discovered_at": 1700000000}
        result = parse_relay_row(row)

        assert isinstance(result, Relay)
        assert result.url == "wss://relay.example.com"
        assert result.network.value == "clearnet"
        assert result.discovered_at == 1700000000

    def test_tor_row(self) -> None:
        """Test constructing a Relay from a Tor DB row."""
        url = "ws://juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion"
        row = {"url": url, "network": "tor", "discovered_at": 1700000000}
        result = parse_relay_row(row)

        assert isinstance(result, Relay)
        assert result.network.value == "tor"

    def test_invalid_url_returns_none(self, caplog: logging.LogRecord) -> None:
        """Test that an invalid URL returns None with warning."""
        row = {"url": "not-valid", "network": "clearnet", "discovered_at": 1700000000}

        with caplog.at_level(logging.WARNING):
            result = parse_relay_row(row)

        assert result is None
        assert "invalid_relay_row_skipped" in caplog.text

    def test_network_mismatch_logs_warning(self, caplog: logging.LogRecord) -> None:
        """Test that network mismatch logs a warning but still returns the relay."""
        row = {"url": "wss://relay.example.com", "network": "tor", "discovered_at": 1700000000}

        with caplog.at_level(logging.WARNING):
            result = parse_relay_row(row)

        assert isinstance(result, Relay)
        assert result.network.value == "clearnet"
        assert "network_mismatch" in caplog.text
        assert "db=tor" in caplog.text
        assert "detected=clearnet" in caplog.text

    def test_network_match_no_warning(self, caplog: logging.LogRecord) -> None:
        """Test that matching network produces no warning."""
        row = {"url": "wss://relay.example.com", "network": "clearnet", "discovered_at": 1700000000}

        with caplog.at_level(logging.WARNING):
            result = parse_relay_row(row)

        assert isinstance(result, Relay)
        assert "network_mismatch" not in caplog.text
