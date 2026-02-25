"""Unit tests for utils.parsing module.

Tests generic model parsing functions (models_from_db_params, models_from_dict).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, NamedTuple


if TYPE_CHECKING:
    import pytest

from bigbrotr.models import Relay
from bigbrotr.models.relay import RelayDbParams
from bigbrotr.utils.parsing import models_from_db_params, models_from_dict


# ============================================================================
# Helpers
# ============================================================================


class _FakeParams(NamedTuple):
    value: str


class _FakeModel:
    """Minimal model with from_db_params for testing."""

    def __init__(self, value: str) -> None:
        if not value:
            raise ValueError("empty value")
        self.value = value

    @classmethod
    def from_db_params(cls, params: _FakeParams) -> _FakeModel:
        return cls(params.value)


# ============================================================================
# TestModelsFromDbParams
# ============================================================================


class TestModelsFromDbParams:
    """Tests for models_from_db_params generic factory."""

    def test_all_valid(self) -> None:
        params = [_FakeParams("a"), _FakeParams("b"), _FakeParams("c")]
        result = models_from_db_params(params, _FakeModel.from_db_params)
        assert [m.value for m in result] == ["a", "b", "c"]

    def test_skips_invalid_entries(self, caplog: pytest.LogCaptureFixture) -> None:
        params = [_FakeParams("ok"), _FakeParams(""), _FakeParams("also_ok")]
        with caplog.at_level(logging.WARNING, logger="bigbrotr.utils.parsing"):
            result = models_from_db_params(params, _FakeModel.from_db_params)
        assert [m.value for m in result] == ["ok", "also_ok"]
        assert "parse_failed" in caplog.text

    def test_empty_list(self) -> None:
        assert models_from_db_params([], _FakeModel.from_db_params) == []

    def test_all_invalid(self, caplog: pytest.LogCaptureFixture) -> None:
        params = [_FakeParams(""), _FakeParams("")]
        with caplog.at_level(logging.WARNING, logger="bigbrotr.utils.parsing"):
            result = models_from_db_params(params, _FakeModel.from_db_params)
        assert result == []
        assert caplog.text.count("parse_failed") == 2

    def test_with_relay_from_db_params(self) -> None:
        params = [RelayDbParams("wss://relay.example.com", "clearnet", 1000)]
        result = models_from_db_params(params, Relay.from_db_params)
        assert len(result) == 1
        assert result[0].url == "wss://relay.example.com"

    def test_with_relay_constructor(self) -> None:
        """Test the pattern used by Pydantic BeforeValidator for config fields."""
        urls = ["wss://valid.example.com", "bad-url", "wss://also-valid.example.com"]
        result = models_from_db_params(urls, Relay)
        assert len(result) == 2
        assert result[0].url == "wss://valid.example.com"
        assert result[1].url == "wss://also-valid.example.com"

    def test_catches_type_error(self, caplog: pytest.LogCaptureFixture) -> None:
        def bad_factory(params: Any) -> _FakeModel:
            raise TypeError("wrong type")

        with caplog.at_level(logging.WARNING, logger="bigbrotr.utils.parsing"):
            result = models_from_db_params([_FakeParams("x")], bad_factory)
        assert result == []
        assert "parse_failed" in caplog.text


# ============================================================================
# TestModelsFromDict
# ============================================================================


class TestModelsFromDict:
    """Tests for models_from_dict generic factory."""

    def test_all_valid(self) -> None:
        rows = [{"url": "wss://r1.example.com"}, {"url": "wss://r2.example.com"}]
        result = models_from_dict(rows, lambda r: Relay(r["url"]))
        assert len(result) == 2
        assert result[0].url == "wss://r1.example.com"
        assert result[1].url == "wss://r2.example.com"

    def test_skips_invalid_entries(self, caplog: pytest.LogCaptureFixture) -> None:
        rows = [
            {"url": "wss://valid.example.com"},
            {"url": "not-a-url"},
            {"url": "wss://also-valid.example.com"},
        ]
        with caplog.at_level(logging.WARNING, logger="bigbrotr.utils.parsing"):
            result = models_from_dict(rows, lambda r: Relay(r["url"]))
        assert len(result) == 2
        assert result[0].url == "wss://valid.example.com"
        assert result[1].url == "wss://also-valid.example.com"
        assert "parse_failed" in caplog.text

    def test_empty_list(self) -> None:
        assert models_from_dict([], lambda r: Relay(r["url"])) == []

    def test_all_invalid(self, caplog: pytest.LogCaptureFixture) -> None:
        rows = [{"url": "bad"}, {"url": "also-bad"}]
        with caplog.at_level(logging.WARNING, logger="bigbrotr.utils.parsing"):
            result = models_from_dict(rows, lambda r: Relay(r["url"]))
        assert result == []
        assert caplog.text.count("parse_failed") == 2

    def test_with_discovered_at(self) -> None:
        rows = [{"url": "wss://relay.example.com", "discovered_at": 1000}]
        result = models_from_dict(rows, lambda r: Relay(r["url"], discovered_at=r["discovered_at"]))
        assert len(result) == 1
        assert result[0].discovered_at == 1000

    def test_catches_type_error(self, caplog: pytest.LogCaptureFixture) -> None:
        def bad_factory(row: dict[str, Any]) -> Relay:
            raise TypeError("wrong type")

        with caplog.at_level(logging.WARNING, logger="bigbrotr.utils.parsing"):
            result = models_from_dict([{"url": "wss://r.example.com"}], bad_factory)
        assert result == []
        assert "parse_failed" in caplog.text

    def test_catches_key_error(self, caplog: pytest.LogCaptureFixture) -> None:
        """KeyError from missing dict key is caught and row is skipped."""
        with caplog.at_level(logging.WARNING, logger="bigbrotr.utils.parsing"):
            result = models_from_dict([{"wrong_key": "x"}], lambda r: Relay(r["url"]))
        assert result == []
        assert "parse_failed" in caplog.text
