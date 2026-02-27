"""Unit tests for utils.parsing module."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    import pytest

from bigbrotr.models import Relay
from bigbrotr.utils.parsing import safe_parse


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
