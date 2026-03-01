"""Unit tests for services.common.utils module.

Tests:
- parse_relay_url: valid URLs, whitespace handling, invalid inputs, edge cases
"""

from __future__ import annotations

from bigbrotr.models import Relay
from bigbrotr.services.common.utils import parse_relay_url


# ============================================================================
# parse_relay_url Tests
# ============================================================================


class TestParseRelayUrl:
    """Tests for parse_relay_url function."""

    def test_valid_wss(self) -> None:
        """Test parsing a valid wss:// URL."""
        result = parse_relay_url("wss://relay.example.com")

        assert isinstance(result, Relay)
        assert result.url == "wss://relay.example.com"

    def test_valid_ws(self) -> None:
        """Test parsing a valid ws:// URL (normalized to wss by Relay)."""
        result = parse_relay_url("ws://relay.example.com")

        assert isinstance(result, Relay)
        assert result.url == "wss://relay.example.com"

    def test_strips_whitespace(self) -> None:
        """Test that leading/trailing whitespace is stripped."""
        result = parse_relay_url("  wss://relay.example.com  ")

        assert isinstance(result, Relay)
        assert result.url == "wss://relay.example.com"

    def test_empty_returns_none(self) -> None:
        """Test that empty string returns None."""
        assert parse_relay_url("") is None

    def test_whitespace_only_returns_none(self) -> None:
        """Test that whitespace-only string returns None."""
        assert parse_relay_url("   ") is None

    def test_none_input_returns_none(self) -> None:
        """Test that None input returns None."""
        assert parse_relay_url(None) is None  # type: ignore[arg-type]

    def test_non_string_returns_none(self) -> None:
        """Test that non-string input returns None."""
        assert parse_relay_url(12345) is None  # type: ignore[arg-type]

    def test_invalid_url_returns_none(self) -> None:
        """Test that invalid URL returns None."""
        assert parse_relay_url("not-a-valid-url") is None

    def test_tor_url(self) -> None:
        """Test parsing a valid .onion relay URL."""
        url = "ws://juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion"
        result = parse_relay_url(url)

        assert isinstance(result, Relay)
        assert result.url == url
