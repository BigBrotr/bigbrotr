"""Unit tests for services.common.utils module.

Tests:
- parse_relay: valid URLs, whitespace handling, invalid inputs, edge cases
- parse_relay_row: DB row construction, network cross-check, invalid rows
"""

from __future__ import annotations

import logging

from bigbrotr.models import Relay
from bigbrotr.services.common.utils import parse_relay, parse_relay_row


# ============================================================================
# parse_relay Tests
# ============================================================================


class TestParseRelayUrl:
    """Tests for parse_relay function."""

    def test_valid_wss(self) -> None:
        """Test parsing a valid wss:// URL."""
        result = parse_relay("wss://relay.example.com")

        assert isinstance(result, Relay)
        assert result.url == "wss://relay.example.com"

    def test_valid_ws(self) -> None:
        """Test parsing a valid ws:// URL (normalized to wss by Relay)."""
        result = parse_relay("ws://relay.example.com")

        assert isinstance(result, Relay)
        assert result.url == "wss://relay.example.com"

    def test_strips_whitespace(self) -> None:
        """Test that leading/trailing whitespace is stripped."""
        result = parse_relay("  wss://relay.example.com  ")

        assert isinstance(result, Relay)
        assert result.url == "wss://relay.example.com"

    def test_empty_returns_none(self) -> None:
        """Test that empty string returns None."""
        assert parse_relay("") is None

    def test_whitespace_only_returns_none(self) -> None:
        """Test that whitespace-only string returns None."""
        assert parse_relay("   ") is None

    def test_none_input_returns_none(self) -> None:
        """Test that None input returns None."""
        assert parse_relay(None) is None  # type: ignore[arg-type]

    def test_non_string_returns_none(self) -> None:
        """Test that non-string input returns None."""
        assert parse_relay(12345) is None  # type: ignore[arg-type]

    def test_invalid_url_returns_none(self) -> None:
        """Test that invalid URL returns None."""
        assert parse_relay("not-a-valid-url") is None

    def test_discovered_at(self) -> None:
        """Test parsing with an explicit discovered_at timestamp."""
        result = parse_relay("wss://relay.example.com", discovered_at=1700000000)

        assert isinstance(result, Relay)
        assert result.discovered_at == 1700000000

    def test_discovered_at_none_uses_default(self) -> None:
        """Test that discovered_at=None lets Relay use current time."""
        result = parse_relay("wss://relay.example.com")

        assert isinstance(result, Relay)
        assert result.discovered_at > 0

    def test_tor_url(self) -> None:
        """Test parsing a valid .onion relay URL."""
        url = "ws://juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion"
        result = parse_relay(url)

        assert isinstance(result, Relay)
        assert result.url == url


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
        assert "Skipping invalid relay URL" in caplog.text

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
