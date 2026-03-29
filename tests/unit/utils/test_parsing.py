"""Unit tests for utils.parsing module."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from bigbrotr.models import Relay
from bigbrotr.utils.parsing import parse_relay_url, safe_parse


# ============================================================================
# TestSafeParse
# ============================================================================


class TestSafeParse:
    """Tests for safe_parse generic factory."""

    def test_all_valid(self) -> None:
        urls = ["wss://r1.example.com", "wss://r2.example.com", "wss://r3.example.com"]
        result = safe_parse(urls, Relay)
        assert [r.url for r in result] == urls

    def test_skips_invalid_entries(self, caplog: pytest.LogCaptureFixture) -> None:
        urls = ["wss://valid.example.com", "bad-url", "wss://also-valid.example.com"]
        with caplog.at_level(logging.WARNING, logger="bigbrotr.utils.parsing"):
            result = safe_parse(urls, Relay)
        assert len(result) == 2
        assert result[0].url == "wss://valid.example.com"
        assert result[1].url == "wss://also-valid.example.com"
        assert "parse_failed" in caplog.text

    def test_empty_list(self) -> None:
        assert safe_parse([], Relay) == []

    def test_all_invalid(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="bigbrotr.utils.parsing"):
            result = safe_parse(["bad", "also-bad"], Relay)
        assert result == []
        assert caplog.text.count("parse_failed") == 2

    def test_with_lambda_factory(self) -> None:
        rows = [{"url": "wss://relay.example.com", "discovered_at": 1000}]
        result = safe_parse(rows, lambda r: Relay(r["url"], discovered_at=r["discovered_at"]))
        assert len(result) == 1
        assert result[0].discovered_at == 1000

    def test_catches_type_error(self, caplog: pytest.LogCaptureFixture) -> None:
        def bad_factory(item: Any) -> Relay:
            raise TypeError("wrong type")

        with caplog.at_level(logging.WARNING, logger="bigbrotr.utils.parsing"):
            result = safe_parse(["wss://r.example.com"], bad_factory)
        assert result == []
        assert "parse_failed" in caplog.text

    def test_catches_key_error(self, caplog: pytest.LogCaptureFixture) -> None:
        """KeyError from missing dict key is caught and item is skipped."""
        with caplog.at_level(logging.WARNING, logger="bigbrotr.utils.parsing"):
            result = safe_parse([{"wrong_key": "x"}], lambda r: Relay(r["url"]))
        assert result == []
        assert "parse_failed" in caplog.text


# ============================================================================
# TestParseRelayUrl
# ============================================================================


class TestParseRelayUrl:
    """Tests for parse_relay_url factory function."""

    def test_clean_url_returns_relay(self):
        relay = parse_relay_url("wss://relay.example.com")
        assert isinstance(relay, Relay)
        assert relay.url == "wss://relay.example.com"

    def test_dirty_url_sanitized(self):
        relay = parse_relay_url("wss://relay.example.com?key=val#frag")
        assert relay.url == "wss://relay.example.com"

    def test_scheme_corrected_for_overlay(self):
        from tests.fixtures.relays import ONION_HOST

        relay = parse_relay_url(f"wss://{ONION_HOST}.onion")
        assert relay.url == f"ws://{ONION_HOST}.onion"
        assert relay.scheme == "ws"

    def test_uppercase_host_lowered(self):
        relay = parse_relay_url("wss://RELAY.EXAMPLE.COM")
        assert relay.url == "wss://relay.example.com"

    def test_default_port_stripped(self):
        relay = parse_relay_url("wss://relay.example.com:443")
        assert relay.url == "wss://relay.example.com"

    def test_explicit_port_preserved(self):
        relay = parse_relay_url("wss://relay.example.com:8080")
        assert relay.url == "wss://relay.example.com:8080"
        assert relay.port == 8080

    def test_path_preserved(self):
        relay = parse_relay_url("wss://relay.example.com/nostr")
        assert relay.path == "/nostr"

    def test_invalid_scheme_raises(self):
        with pytest.raises(ValueError):
            parse_relay_url("http://relay.example.com")

    def test_no_host_raises(self):
        with pytest.raises(ValueError):
            parse_relay_url("wss://")

    def test_local_address_raises(self):
        with pytest.raises(ValueError):
            parse_relay_url("wss://127.0.0.1")
